# -*- coding: utf-8 -*-
"""PostgreSQL-backed read path for scroll recall (M2 "reads on pg" step).

``MemorySpace`` gives the model a SQLite scratch space with the durable
history ATTACHed read-only — including an arbitrary-SQL hatch. On a shared
multi-user PostgreSQL that hatch cannot be owner-enforced, so this class
implements the *structured* recall surface only:

- ``expand`` / ``recall_tool`` / ``sessions`` / ``session`` / ``agents``
- ``search`` with tsvector ranking, LIKE fallback for CJK and punctuation
  queries, active-turn exclusion, distinct-turn paging and turn expansion

``sql_query``/``sql_exec`` raise ``NotImplementedError`` by design; the
saved-tool-file artifact fallback is not part of the first pg iteration
(DB hits carry the recall load). Like ``PgHistoryStore`` it owns a private
engine on a dedicated loop thread (asyncpg loop affinity) behind a
synchronous façade, matching how the recall tools call it.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from ....db.async_bridge import AsyncLoopThread
from .memoryspace import (
    _CJK_QUERY_RE,
    _RECALL_TOOL_NAMES,
    _SYNTHETIC_USER_TAGS,
    _like_pattern,
    _like_search_groups,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_DEFAULT_ROW_CAP = 200
_TURN_BOUNDARY_BATCH_SIZE = 50
_DEFAULT_SEARCH_TURN_MAX_ROWS = 400
_DEFAULT_SEARCH_TURN_MAX_BYTES = 256 * 1024
_DEFAULT_SEARCH_MAX_SECONDS = 15.0

# A query with no word characters cannot form a tsquery term.
_WORD_RE = re.compile(r"\w", re.UNICODE)


class _Query:
    """Named-parameter WHERE builder (SQLAlchemy ``text()`` compatible)."""

    def __init__(self) -> None:
        self.where: list[str] = []
        self.params: dict[str, Any] = {}
        self._n = 0

    def add(self, template: str, *values: Any) -> None:
        """Add ``template`` with its ``?`` placeholders bound in order."""
        clause = template
        for value in values:
            name = f"p{self._n}"
            self._n += 1
            self.params[name] = value
            clause = clause.replace("?", f":{name}", 1)
        self.where.append(clause)


def _pg_dt(value: Any) -> datetime | None:
    """Normalize an ISO string/datetime to an aware datetime for asyncpg."""
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class PgMemorySpace:
    """Synchronous, owner-scoped recall reader over ``history_entries``."""

    def __init__(
        self,
        *,
        dsn: str,
        session_id: str | None = None,
        agent_id: str | None = None,
        owner_id: str | None = None,
        tenant_id: str = "default",
        row_cap: int = _DEFAULT_ROW_CAP,
        search_turn_max_rows: int = _DEFAULT_SEARCH_TURN_MAX_ROWS,
        search_turn_max_bytes: int = _DEFAULT_SEARCH_TURN_MAX_BYTES,
        search_max_seconds: float = _DEFAULT_SEARCH_MAX_SECONDS,
    ) -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._session_id = session_id
        self._agent_id = agent_id
        # M1: every query constrains to this owner's rows; never widen.
        self._owner_id = owner_id
        self._row_cap = row_cap
        self._search_turn_max_rows = max(0, int(search_turn_max_rows))
        self._search_turn_max_bytes = max(0, int(search_turn_max_bytes))
        self._search_max_seconds = max(0.0, float(search_max_seconds))
        self._floor_cache: int | None = None
        self._floor_computed = False
        self._closed = False
        self._loop = AsyncLoopThread(thread_name="qwenpaw-pg-memoryspace")
        self._engine = self._loop.run(self._create_engine())

    async def _create_engine(self) -> "AsyncEngine":
        from sqlalchemy.ext.asyncio import create_async_engine

        return create_async_engine(
            self._dsn,
            pool_size=2,
            max_overflow=2,
            pool_pre_ping=True,
        )

    # -- lifecycle -----------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def agent_id(self) -> str | None:
        return self._agent_id

    def refresh(self) -> None:
        """Reset per-query memoization so a reused instance sees new rows.

        The active-turn floor is memoized per *query session*: a long-lived
        reused instance must drop it before each new recall op, or a turn
        that started after the first call would never become searchable.
        """
        self._floor_cache = None
        self._floor_computed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run(self._engine.dispose())
        except Exception:  # noqa: BLE001 - teardown must not raise
            pass
        self._loop.close()

    # -- no arbitrary SQL on a shared multi-user database ----------------------

    def sql_query(self, sql: str, params=None) -> list[dict]:
        """Disabled by design (see module docstring)."""
        raise NotImplementedError(
            "PgMemorySpace does not expose arbitrary SQL: on a multi-user "
            "PostgreSQL an owner predicate cannot be enforced inside a "
            "free-form query. Use the structured recall methods (search / "
            "expand / session / sessions / recall_tool / agents).",
        )

    def sql_exec(self, sql: str, params=None) -> int:
        """Disabled by design (see module docstring)."""
        raise NotImplementedError(
            "PgMemorySpace is read-only; sql_exec is unavailable.",
        )

    def days_between(self, d1: object, d2: object, *, inclusive=False) -> int:
        """Signed calendar-day difference (pure Python, no DB access)."""
        from .memoryspace import parse_date

        difference = (parse_date(d2) - parse_date(d1)).days
        if not inclusive:
            return difference
        return difference + 1 if difference >= 0 else difference - 1

    # -- query plumbing ----------------------------------------------------------

    async def _select(self, sql: str, params: dict) -> list[dict]:
        """Run a read query, capped at ``row_cap`` rows (+truncation flag)."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows: list[dict] = []
            for i, row in enumerate(result):
                if i >= self._row_cap:
                    rows.append(
                        {"_truncated": True, "_row_cap": self._row_cap},
                    )
                    break
                rows.append(dict(row._mapping))
        return rows

    def _run(self, coro):
        return self._loop.run(coro)

    def _scope(self, q: _Query, *, all_agents: bool = False) -> None:
        """Apply tenant + agent + owner lineage to the query under build."""
        q.add("tenant_id = ?", self._tenant_id)
        if not all_agents and self._agent_id:
            q.add("agent_id = ?", self._agent_id)
        if self._owner_id:
            q.add("owner_id = ?", self._owner_id)

    # -- structured recall -------------------------------------------------------

    def expand(self, lo: int, hi: int) -> list[dict]:
        """Full durable turns in the seq span ``[lo, hi]``, oldest first."""
        q = _Query()
        q.where.append("seq BETWEEN :lo AND :hi")
        q.params["lo"] = int(lo)
        q.params["hi"] = int(hi)
        q.add("tenant_id = ?", self._tenant_id)
        if self._session_id:
            q.add("session_id = ?", self._session_id)
        if self._agent_id:
            q.add("(agent_id = ? OR agent_id IS NULL)", self._agent_id)
        if self._owner_id:
            q.add("owner_id = ?", self._owner_id)
        return self._run(
            self._select(
                "SELECT seq, kind, role, name, content, headline, "
                "blocks::text AS blocks, metadata::text AS metadata, "
                "created_at FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " ORDER BY seq",
                q.params,
            ),
        )

    def recall_tool(
        self,
        tool_call_id: str,
        *,
        all_agents: bool = False,
    ) -> list[dict]:
        """Re-read a tool call and its result by ``tool_call_id``."""
        q = _Query()
        q.add("tool_call_id = ?", str(tool_call_id))
        self._scope(q, all_agents=all_agents)
        return self._run(
            self._select(
                "SELECT seq, kind, role, name, tool_input::text AS "
                "tool_input, tool_state, content, blocks::text AS blocks, "
                "metadata::text AS metadata, created_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " ORDER BY seq",
                q.params,
            ),
        )

    def sessions(
        self,
        *,
        all_agents: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        """List conversations in durable history (turn/seq/time spans)."""
        q = _Query()
        self._scope(q, all_agents=all_agents)
        return self._run(
            self._select(
                "SELECT session_id, COUNT(*) AS turns, MIN(seq) AS "
                "first_seq, MAX(seq) AS last_seq, MAX(created_at) AS last_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " GROUP BY session_id ORDER BY last_seq DESC LIMIT :lim",
                {**q.params, "lim": int(limit)},
            ),
        )

    def session(
        self,
        session_id: str,
        *,
        all_agents: bool = False,
        limit: int = 200,
    ) -> list[dict]:
        """Read one conversation's turns oldest-first."""
        q = _Query()
        q.add("session_id = ?", str(session_id))
        self._scope(q, all_agents=all_agents)
        return self._run(
            self._select(
                "SELECT seq, kind, role, name, headline, content, created_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " ORDER BY seq LIMIT :lim",
                {**q.params, "lim": int(limit)},
            ),
        )

    def agents(self, *, limit: int = 50) -> list[dict]:
        """List agents that have written history (owner-scoped, M1)."""
        q = _Query()
        q.add("tenant_id = ?", self._tenant_id)
        if self._owner_id:
            q.add("owner_id = ?", self._owner_id)
        return self._run(
            self._select(
                "SELECT agent_id, COUNT(DISTINCT session_id) AS sessions, "
                "COUNT(*) AS turns, MAX(created_at) AS last_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " GROUP BY agent_id ORDER BY last_at DESC LIMIT :lim",
                {**q.params, "lim": int(limit)},
            ),
        )

    # -- search ----------------------------------------------------------------

    def _active_turn_floor(self) -> int | None:
        """Seq of the current session's latest real user row, or None."""
        if self._floor_computed:
            return self._floor_cache
        self._floor_computed = True
        if not self._session_id:
            return None
        q = _Query()
        q.add("session_id = ?", self._session_id)
        q.add("kind = ?", "context_msg")
        q.add("role = ?", "user")
        if self._agent_id:
            q.add("agent_id = ?", self._agent_id)
        self._scope_owner_only(q)
        for tag in _SYNTHETIC_USER_TAGS:
            q.add(
                "(metadata IS NULL OR metadata::text NOT LIKE ?)",
                f'%"{tag}"%',
            )
        rows = self._run(
            self._select(
                "SELECT MAX(seq) AS s FROM history_entries WHERE "
                + " AND ".join(q.where),
                q.params,
            ),
        )
        self._floor_cache = (
            int(rows[0]["s"]) if rows and rows[0]["s"] is not None else None
        )
        return self._floor_cache

    def _scope_owner_only(self, q: _Query) -> None:
        q.add("tenant_id = ?", self._tenant_id)
        if self._owner_id:
            q.add("owner_id = ?", self._owner_id)

    def _active_turn_exclusion(self, q: _Query) -> None:
        """Exclude the in-progress turn from search candidates."""
        floor = self._active_turn_floor()
        if floor is None:
            return
        conds = ["session_id = :excl_sid"]
        params: dict[str, Any] = {
            "excl_sid": self._session_id,
            "excl_floor": floor,
        }
        if self._agent_id:
            conds.append("agent_id = :excl_aid")
            params["excl_aid"] = self._agent_id
        conds.append("seq >= :excl_floor")
        q.where.append("NOT (" + " AND ".join(conds) + ")")
        q.params.update(params)

    def _created_conditions(
        self,
        q: _Query,
        created_on: str | None,
        created_from: str | None,
        created_to: str | None,
    ) -> None:
        if created_on is not None and (
            created_from is not None or created_to is not None
        ):
            raise ValueError(
                "created_on cannot be combined with created_from/created_to",
            )
        if created_on is not None:
            day = date.fromisoformat(created_on)
            created_from = day.isoformat()
            created_to = (day + timedelta(days=1)).isoformat()
        if created_from:
            q.add("created_at >= ?", created_from)
        if created_to:
            q.add("created_at < ?", created_to)

    def _base_search_where(
        self,
        q: _Query,
        targets: list[tuple[str, str]],
        kind: str | None,
        created_on: str | None,
        created_from: str | None,
        created_to: str | None,
    ) -> None:
        """Shared predicates: recall-tool exclusion, scope, dates, kind."""
        names = ", ".join(f":rt{i}" for i in range(len(_RECALL_TOOL_NAMES)))
        q.where.append(f"(name IS NULL OR name NOT IN ({names}))")
        for i, name in enumerate(_RECALL_TOOL_NAMES):
            q.params[f"rt{i}"] = name
        self._active_turn_exclusion(q)
        for col, val in targets:
            q.add(f"{col} = ?", val)
        self._created_conditions(q, created_on, created_from, created_to)
        if kind:
            q.add("kind = ?", kind)

    def _scope_filters(
        self,
        all_agents: bool,
        session_id: str | None,
        agent_id: str | None,
    ) -> list[tuple[str, str]]:
        """Resolve lineage filters; owner is always ANDed on top (M1)."""
        pinned: list[tuple[str, str]] = [("tenant_id", self._tenant_id)]
        if session_id is not None or agent_id is not None:
            if session_id is not None:
                pinned.append(("session_id", session_id))
            if agent_id is not None:
                pinned.append(("agent_id", agent_id))
        elif all_agents:
            pass
        elif self._agent_id:
            pinned.append(("agent_id", self._agent_id))
        if self._owner_id:
            pinned.append(("owner_id", self._owner_id))
        return pinned

    def _search_fts_rows(
        self,
        query: str,
        targets: list[tuple[str, str]],
        kind: str | None,
        limit: int,
        *,
        offset: int = 0,
        created_on: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict]:
        """One tsvector-ranked page of raw hits ('simple' config: CJK-safe
        tokenization lives in the LIKE path instead)."""
        q = _Query()
        q.where.append("tsv @@ plainto_tsquery('simple', :tsq)")
        q.params["tsq"] = query
        self._base_search_where(
            q,
            targets,
            kind,
            created_on,
            created_from,
            created_to,
        )
        return self._run(
            self._select(
                "SELECT seq, session_id, agent_id, kind, role, name, "
                "headline, content, metadata::text AS metadata, created_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " ORDER BY ts_rank(tsv, plainto_tsquery('simple', :tsq)) "
                "DESC, seq LIMIT :lim OFFSET :off",
                {**q.params, "lim": int(limit), "off": int(offset)},
            ),
        )

    def _search_like_rows(
        self,
        query: str,
        targets: list[tuple[str, str]],
        kind: str | None,
        limit: int,
        *,
        offset: int = 0,
        created_on: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict]:
        """Literal-substring page (CJK / punctuation-only queries)."""
        q = _Query()
        groups = _like_search_groups(query)
        clauses: list[str] = []
        for terms in groups:
            parts = []
            for term in terms:
                name = f"lk{q._n}"
                q._n += 1
                q.params[name] = _like_pattern(term)
                parts.append(f"content LIKE :{name} ESCAPE '\\'")
            clauses.append("(" + " AND ".join(parts) + ")")
        q.where.append("(" + " OR ".join(clauses) + ")")
        self._base_search_where(
            q,
            targets,
            kind,
            created_on,
            created_from,
            created_to,
        )
        return self._run(
            self._select(
                "SELECT seq, session_id, agent_id, kind, role, name, "
                "headline, content, metadata::text AS metadata, created_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " ORDER BY seq DESC LIMIT :lim OFFSET :off",
                {**q.params, "lim": int(limit), "off": int(offset)},
            ),
        )

    def _search_date_rows(
        self,
        targets: list[tuple[str, str]],
        kind: str | None,
        limit: int,
        *,
        offset: int = 0,
        created_on: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict]:
        """Date-only recall page (empty query)."""
        q = _Query()
        self._base_search_where(
            q,
            targets,
            kind,
            created_on,
            created_from,
            created_to,
        )
        return self._run(
            self._select(
                "SELECT seq, session_id, agent_id, kind, role, name, "
                "headline, content, metadata::text AS metadata, created_at "
                "FROM history_entries WHERE "
                + " AND ".join(q.where)
                + " ORDER BY seq DESC LIMIT :lim OFFSET :off",
                {**q.params, "lim": int(limit), "off": int(offset)},
            ),
        )

    # -- turn expansion ------------------------------------------------------

    def _real_user_conditions(self, q: _Query, prefix: str = "") -> None:
        """User-boundary predicates (tagged stubs never open a turn)."""
        q.where.append(f"{prefix}role = 'user'")
        for i, tag in enumerate(_SYNTHETIC_USER_TAGS):
            name = f"tag{q._n}"
            q._n += 1
            q.params[name] = f'%"{tag}"%'
            q.where.append(
                f"({prefix}metadata IS NULL OR {prefix}metadata::text "
                f"NOT LIKE :{name})",
            )

    def _turn_start_seqs(
        self,
        rows: list[dict],
        deadline: float,
    ) -> dict[int, int | None]:
        """Resolve hit seq -> its turn's opening user-row seq."""
        hit_seqs = list(
            dict.fromkeys(
                int(row["seq"])
                for row in rows
                if not row.get("_truncated") and int(row.get("seq", -1)) >= 0
            ),
        )
        starts: dict[int, int | None] = {}
        for offset in range(0, len(hit_seqs), _TURN_BOUNDARY_BATCH_SIZE):
            if time.monotonic() > deadline:
                break
            batch = hit_seqs[offset : offset + _TURN_BOUNDARY_BATCH_SIZE]
            q = _Query()
            for i, seq in enumerate(batch):
                q.params[f"b{i}"] = seq
            names = ", ".join(f":b{i}" for i in range(len(batch)))
            sub = _Query()
            self._real_user_conditions(sub, "b.")
            sql = (
                "SELECT hit.seq AS hit_seq, "
                "(SELECT MAX(b.seq) FROM history_entries b WHERE "
                "b.tenant_id = hit.tenant_id "
                "AND b.session_id = hit.session_id "
                "AND b.agent_id IS NOT DISTINCT FROM hit.agent_id AND "
                + " AND ".join(sub.where)
                + " AND b.seq <= hit.seq) AS start_seq "
                "FROM history_entries hit "
                f"WHERE hit.tenant_id = :tid AND hit.seq IN ({names})"
            )
            params = {**q.params, **sub.params, "tid": self._tenant_id}
            for row in self._run(self._select(sql, params)):
                starts[int(row["hit_seq"])] = (
                    int(row["start_seq"])
                    if row["start_seq"] is not None
                    else None
                )
        return starts

    def _load_turn(
        self,
        hit: dict,
        start_seq: int | None,
        budget_rows: list[int],
        budget_bytes: list[int],
    ) -> tuple[int, int, int | None, bool, list[dict]]:
        """Load one deduplicated turn under the shared row/byte budget."""
        hit_seq = int(hit["seq"])
        q = _Query()
        q.add("tenant_id = ?", self._tenant_id)
        q.add("session_id = ?", hit.get("session_id"))
        q.where.append("agent_id IS NOT DISTINCT FROM :agent_v")
        q.params["agent_v"] = hit.get("agent_id")
        # M1: never let turn expansion pull another owner's rows.
        if self._owner_id:
            q.where.append("owner_id IS NOT DISTINCT FROM :owner_v")
            q.params["owner_v"] = self._owner_id
        select_columns = (
            "seq, session_id, agent_id, kind, role, name, headline, "
            "content, blocks::text AS blocks, tool_call_id, "
            "tool_input::text AS tool_input, tool_state, "
            "metadata::text AS metadata, created_at"
        )

        if start_seq is None:
            q.where.append("seq = :hit_seq")
            q.params["hit_seq"] = hit_seq
            rows = self._run(
                self._select(
                    f"SELECT {select_columns} FROM history_entries WHERE "
                    + " AND ".join(q.where),
                    q.params,
                ),
            )
            effective_start = hit_seq
            actual_end = hit_seq
        else:
            boundary = _Query()
            boundary.add("tenant_id = ?", self._tenant_id)
            boundary.add("session_id = ?", hit.get("session_id"))
            boundary.where.append("agent_id IS NOT DISTINCT FROM :agent_v")
            boundary.params["agent_v"] = hit.get("agent_id")
            if self._owner_id:
                boundary.where.append("owner_id IS NOT DISTINCT FROM :owner_v")
                boundary.params["owner_v"] = self._owner_id
            self._real_user_conditions(boundary)
            boundary.where.append("seq > :start_v")
            boundary.params["start_v"] = int(start_seq)
            next_rows = self._run(
                self._select(
                    "SELECT MIN(seq) AS seq FROM history_entries WHERE "
                    + " AND ".join(boundary.where),
                    boundary.params,
                ),
            )
            next_user_seq = (
                next_rows[0]["seq"]
                if next_rows and next_rows[0]["seq"] is not None
                else None
            )
            q.where.append("seq >= :start_v")
            q.params["start_v"] = int(start_seq)
            if next_user_seq is not None:
                q.where.append("seq < :next_v")
                q.params["next_v"] = int(next_user_seq)
            end_rows = self._run(
                self._select(
                    "SELECT MAX(seq) AS seq FROM history_entries WHERE "
                    + " AND ".join(q.where),
                    q.params,
                ),
            )
            actual_end = (
                int(end_rows[0]["seq"])
                if end_rows and end_rows[0]["seq"] is not None
                else hit_seq
            )
            rows = self._run(
                self._select(
                    f"SELECT {select_columns} FROM history_entries WHERE "
                    + " AND ".join(q.where)
                    + " ORDER BY seq",
                    q.params,
                ),
            )
            effective_start = int(start_seq)

        turn: list[dict] = []
        for row in rows:
            if row.get("_truncated"):
                turn.append(row)
                break
            cost = len(str(row.get("content") or "").encode("utf-8"))
            if budget_rows[0] <= 0 or budget_bytes[0] - cost < 0:
                turn.append(
                    {
                        "_truncated": True,
                        "_row_cap": self._search_turn_max_rows,
                        "_reason": "search turn budget exhausted",
                    },
                )
                break
            budget_rows[0] -= 1
            budget_bytes[0] -= cost
            turn.append(row)
        real_rows = [r for r in turn if not r.get("_truncated")]
        if not real_rows:
            if not turn:
                return hit_seq, hit_seq, hit_seq, True, [dict(hit)]
            return effective_start, actual_end, None, False, turn
        loaded_end = int(real_rows[-1]["seq"])
        complete = loaded_end == actual_end and all(
            not r.get("_truncated") for r in turn
        )
        return effective_start, actual_end, loaded_end, complete, turn

    def _attach_search_turns(
        self,
        rows: list[dict],
        limit: int,
        deadline: float,
        budget_rows: list[int],
        budget_bytes: list[int],
    ) -> list[dict]:
        """Deduplicate by turn, then load each selected turn once."""
        starts = self._turn_start_seqs(rows, deadline)
        notices: list[dict] = []
        groups: dict[tuple, dict] = {}
        for row in rows:
            if row.get("_truncated") or int(row.get("seq", -1)) < 0:
                notices.append(row)
                continue
            seq = int(row["seq"])
            start = starts.get(seq)
            key = (
                row.get("session_id"),
                row.get("agent_id"),
                start if start is not None else seq,
            )
            group = groups.setdefault(
                key,
                {"hit": row, "start": start, "matched_seqs": []},
            )
            group["matched_seqs"].append(seq)
        results: list[dict] = []
        for group in list(groups.values())[:limit]:
            start, end, loaded_end, complete, turn = self._load_turn(
                group["hit"],
                group["start"],
                budget_rows,
                budget_bytes,
            )
            hit_row = dict(group["hit"])
            hit_row.update(
                {
                    "turn_start_seq": start,
                    "turn_end_seq": end,
                    "turn_loaded_end_seq": loaded_end,
                    "turn_complete": complete,
                    "matched_seqs": group["matched_seqs"],
                    "turn": turn,
                },
            )
            results.append(hit_row)
        return [*notices, *results]

    # -- public search ---------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        all_agents: bool = False,
        kind: str | None = None,
        k: int = 10,
        include_turn: bool = True,
        created_on: str | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> list[dict]:
        """Bounded owner-scoped history search over the tsvector index.

        Falls back to a literal LIKE scan for CJK or punctuation-only
        queries (the 'simple' tsconfig does not segment CJK). The agent's
        ACTIVE TURN is excluded; earlier evicted turns stay searchable.
        """
        requested = max(0, int(k))
        if requested == 0:
            return []
        deadline = time.monotonic() + self._search_max_seconds
        budget_rows = [self._search_turn_max_rows]
        budget_bytes = [self._search_turn_max_bytes]
        targets = self._scope_filters(all_agents, session_id, agent_id)
        date_args = {
            "created_on": created_on,
            "created_from": created_from,
            "created_to": created_to,
        }

        # LIKE path: CJK (unsegmented by 'simple' tsconfig) or queries with
        # no word tokens at all (plainto_tsquery would return an empty
        # tsquery and silently match nothing).
        use_like = (
            not query
            or _CJK_QUERY_RE.search(query) is not None
            or not _WORD_RE.search(query)
        )
        if not query.strip():
            page = self._search_date_rows(
                targets,
                kind,
                min(requested, self._row_cap),
                **date_args,
            )
            if not include_turn:
                return page
        elif use_like:
            page = self._search_like_rows(
                query,
                targets,
                kind,
                min(requested, self._row_cap),
                **date_args,
            )
            if not include_turn:
                return page[:requested]
        else:
            page = self._search_fts_rows(
                query,
                targets,
                kind,
                min(requested, self._row_cap),
                **date_args,
            )
            if not include_turn:
                return page[:requested]
        return self._attach_search_turns(
            page,
            requested,
            deadline,
            budget_rows,
            budget_bytes,
        )
