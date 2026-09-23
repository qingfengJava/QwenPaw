# -*- coding: utf-8 -*-
"""Backfill ``agent_documents`` from every agent workspace's identity files.

``agent_documents`` is the Phase A shadow store for the four identity files
(``PROFILE.md`` / ``AGENTS.md`` / ``SOUL.md`` / ``agent.json``). Writes made
after the table existed are mirrored automatically (fire-and-forget shadow
write in :mod:`qwenpaw.app.agent_docs.store`), but rows that predate the
table — every workspace file — are absent from PostgreSQL until this script
runs. Phase B (read switch) must not start before the backfill is done.

Discovery reuses the same workspace sweep as ``backfill_chat_agent``:
config-driven profiles first, then a heuristic over the workspaces root
(orphan agent dirs, the ``experts/`` tree, ``.drafts`` sub-tree). Draft ids
(``expert_<id>__draft``) map to the ``draft`` environment automatically.

Idempotent: upserts are keyed on content hash, so re-running the script
never bumps ``version`` nor rewrites unchanged content.

Usage::

    python -m qwenpaw.db.backfill_agent_docs [--dry-run]

@author qingfeng
"""

from __future__ import annotations

import asyncio
import logging

from ..app.agent_docs.store import AgentDocsStore

logger = logging.getLogger(__name__)

#: 与 agent_docs.store.DOC_TYPE_BY_FILENAME 保持一致（文件名 → doc_type）
DOC_TYPE_BY_FILENAME = {
    "PROFILE.md": "profile",
    "AGENTS.md": "agents",
    "SOUL.md": "soul",
    "agent.json": "agent_json",
}

#: 影子行的操作者标识（与在线影子写区分，便于审计排查）
_BACKFILL_ACTOR = "backfill_agent_docs"


def _collect_documents(ws_dir) -> dict[str, str]:
    """Read the identity files of one workspace into {doc_type: content}."""
    documents: dict[str, str] = {}
    for filename, doc_type in DOC_TYPE_BY_FILENAME.items():
        path = ws_dir / filename
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping unreadable %s: %s", path, exc)
            continue
        if content.strip():
            documents[doc_type] = content
    return documents


async def _run(dry_run: bool) -> int:
    from .backfill_chat_agent import _agent_workspace_pairs

    pairs = _agent_workspace_pairs()
    print(f"workspaces discovered: {len(pairs)}")

    store = AgentDocsStore()
    total_docs = 0
    written_docs = 0
    for agent_id, ws_dir in pairs:
        documents = _collect_documents(ws_dir)
        total_docs += len(documents)
        docs_desc = ", ".join(
            f"{doc_type}({len(content)}ch)"
            for doc_type, content in documents.items()
        )
        if not documents:
            print(f"  {agent_id} -> {ws_dir}  [no identity files]")
            continue
        if dry_run:
            print(f"  {agent_id} -> {ws_dir}  plan: {docs_desc}")
            continue
        written = await store.upsert_documents(
            agent_id,
            documents,
            updated_by=_BACKFILL_ACTOR,
        )
        written_docs += written
        print(f"  {agent_id} -> {ws_dir}  written={written}  {docs_desc}")

    if dry_run:
        print(f"\n=== agent_documents backfill DRY-RUN ===")
        print(f"  workspaces={len(pairs)} docs_found={total_docs}")
    else:
        print("\n=== agent_documents backfill APPLIED ===")
        print(f"  workspaces={len(pairs)} docs_found={total_docs} "
              f"docs_written={written_docs}")
        print("  (re-run is safe: unchanged content never bumps version)")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the import plan without writing",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
