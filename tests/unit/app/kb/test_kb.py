# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for the M4-5 knowledge base service and retrieval."""
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.kb.models import (
    SCOPE_ENTERPRISE,
    SCOPE_PERSONAL,
    SCOPE_TEAM,
)
from qwenpaw.app.kb.search import _tokenize, search_chunks
from qwenpaw.app.kb.service import KbService, chunk_text


@pytest.fixture
def service(tmp_path: Path) -> KbService:
    return KbService(
        registry_path=tmp_path / "kb_registry.json",
        data_dir=tmp_path / "kb_data",
    )


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


def test_chunk_text_packs_paragraphs() -> None:
    text = "\n\n".join(f"paragraph {i} " + "x" * 200 for i in range(10))
    chunks = chunk_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= 900 for c in chunks)
    # Overlap keeps boundary context.
    assert chunks[1][:50] in chunks[0] or chunks[1].startswith("paragraph")


def test_chunk_text_hard_splits_giant_paragraph() -> None:
    text = "y" * 10000  # no blank lines at all
    chunks = chunk_text(text)
    assert len(chunks) >= 3
    assert all(len(c) <= 3200 for c in chunks)


def test_chunk_text_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("\n\n\n") == []


# ---------------------------------------------------------------------------
# tokenizer / retrieval
# ---------------------------------------------------------------------------


def test_tokenize_handles_cjk_bigrams() -> None:
    tokens = _tokenize("数据库 PostgreSQL 选型")
    assert "postg resql".split()[0] not in tokens  # sanity
    assert "postg" not in tokens
    assert "postgresql" in tokens
    # CJK content becomes bigrams.
    assert "数据" in tokens and "据库" in tokens


def _chunks(service: KbService, kb_id: str):
    return service._load_chunks(kb_id)


def test_bm25_ranks_relevant_chunk(service: KbService) -> None:
    kb = service.create_kb("lib", scope=SCOPE_PERSONAL, owner_id="alice")
    service.ingest_text(
        kb.id,
        "The migration moved the primary store to PostgreSQL.\n\n"
        "SQLite remains the developer-only fallback.\n\n"
        "Redis was rejected for this stage.",
        title="storage decision",
    )
    chunks = _chunks(service, kb.id)
    hits = search_chunks(chunks, "PostgreSQL migration", top_k=2)
    assert hits
    assert "PostgreSQL" in hits[0][0].text


def test_vector_branch_breaks_keyword_ties(service: KbService) -> None:
    kb = service.create_kb("lib", scope=SCOPE_PERSONAL, owner_id="alice")
    # Two chunks with no shared tokens with the query.
    service.ingest_text(kb.id, "alpha beta gamma", title="t1")
    service.ingest_text(kb.id, "delta epsilon zeta", title="t2")
    chunks = _chunks(service, kb.id)
    query_embedding = [1.0, 0.0]
    chunks[0].embedding = [0.9, 0.1]
    chunks[1].embedding = [0.0, 1.0]
    hits = search_chunks(
        chunks,
        "unrelated query",
        query_embedding=query_embedding,
        top_k=1,
    )
    assert hits[0][0].text == "alpha beta gamma"


def test_search_empty_query_returns_nothing(service: KbService) -> None:
    kb = service.create_kb("lib", scope=SCOPE_PERSONAL, owner_id="alice")
    service.ingest_text(kb.id, "some content")
    assert service.search(kb.id, "") == []


# ---------------------------------------------------------------------------
# ACL
# ---------------------------------------------------------------------------


def test_personal_scope_owner_only(service: KbService) -> None:
    kb = service.create_kb("mine", scope=SCOPE_PERSONAL, owner_id="alice")
    assert service.can_access(kb, "alice") is True
    assert service.can_access(kb, "bob") is False
    assert service.can_access(kb, "") is False
    # flat admin sees everything.
    assert service.can_access(kb, "root", flat_role="admin") is True


def test_team_scope_members_only(service: KbService) -> None:
    kb = service.create_kb("teamlib", scope=SCOPE_TEAM, team_id="core")
    assert service.can_access(kb, "alice", user_teams=["core"]) is True
    assert service.can_access(kb, "bob", user_teams=["edge"]) is False


def test_enterprise_scope_any_authenticated(service: KbService) -> None:
    kb = service.create_kb("public", scope=SCOPE_ENTERPRISE)
    assert service.can_access(kb, "anyone") is True
    assert service.can_access(kb, "") is False


def test_explicit_grants_extend_scope(service: KbService) -> None:
    kb = service.create_kb("mine", scope=SCOPE_PERSONAL, owner_id="alice")
    service.update_grants(kb.id, users=["bob"], roles=["team_lead"])
    kb = service.get_kb(kb.id)
    assert service.can_access(kb, "bob") is True
    assert service.can_access(kb, "eve", user_roles=["team_lead"]) is True
    assert service.can_access(kb, "mallory") is False


def test_accessible_kbs_filtering(service: KbService) -> None:
    mine = service.create_kb("mine", scope=SCOPE_PERSONAL, owner_id="alice")
    team = service.create_kb("teamlib", scope=SCOPE_TEAM, team_id="core")
    public = service.create_kb("public", scope=SCOPE_ENTERPRISE)
    other = service.create_kb("other", scope=SCOPE_PERSONAL, owner_id="bob")

    visible = service.accessible_kbs("alice", user_teams=["core"])
    ids = {kb.id for kb in visible}
    assert mine.id in ids and team.id in ids and public.id in ids
    assert other.id not in ids


# ---------------------------------------------------------------------------
# ingestion lifecycle
# ---------------------------------------------------------------------------


def test_ingest_and_delete_document(service: KbService) -> None:
    kb = service.create_kb("lib", scope=SCOPE_PERSONAL, owner_id="alice")
    doc = service.ingest_text(kb.id, "first document body", title="d1")
    assert doc is not None and doc.chunk_count >= 1
    assert len(service.list_documents(kb.id)) == 1

    assert service.delete_document(doc.doc_id) is True
    assert service.list_documents(kb.id) == []
    assert service._load_chunks(kb.id) == []


def test_delete_kb_removes_chunks(service: KbService) -> None:
    kb = service.create_kb("lib", scope=SCOPE_PERSONAL, owner_id="alice")
    service.ingest_text(kb.id, "payload")
    assert service._chunks_path(kb.id).exists()
    assert service.delete_kb(kb.id) is True
    assert not service._chunks_path(kb.id).exists()
    assert service.get_kb(kb.id) is None


def test_ingest_into_missing_kb_rejected(service: KbService) -> None:
    assert service.ingest_text("kb_nope", "text") is None


# ---------------------------------------------------------------------------
# kb_search tool
# ---------------------------------------------------------------------------


def _hit_text(chunk) -> str:
    block = chunk.content[0]
    if isinstance(block, dict):
        return block["text"]
    return getattr(block, "text", "")


async def test_kb_search_tool_acl(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.kb.tool import make_kb_search_tool

    mine = service.create_kb("mine", scope=SCOPE_PERSONAL, owner_id="alice")
    service.ingest_text(mine.id, "Alice's private deployment notes")
    other = service.create_kb("other", scope=SCOPE_PERSONAL, owner_id="bob")
    service.ingest_text(other.id, "Bob's private runbook")

    import qwenpaw.app.kb.tool as tool_module

    monkeypatch.setattr(
        tool_module,
        "_current_identity",
        lambda: ("alice", {"flat_role": "employee", "user_roles": [], "user_teams": []}),
    )
    tool = make_kb_search_tool(service)
    result = await tool("deployment notes")
    text = _hit_text(result)
    assert "Alice" in text
    assert "Bob" not in text

    # Searching an inaccessible kb by id is refused.
    denied = await tool("runbook", kb_id=other.id)
    assert "do not have access" in _hit_text(denied)

    # Unknown kb id errors out.
    missing = await tool("x", kb_id="kb_nope")
    assert "not found" in _hit_text(missing)


async def test_kb_search_tool_no_bases(
    service: KbService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qwenpaw.app.kb.tool import make_kb_search_tool
    import qwenpaw.app.kb.tool as tool_module

    monkeypatch.setattr(
        tool_module,
        "_current_identity",
        lambda: ("alice", {}),
    )
    tool = make_kb_search_tool(service)
    result = await tool("anything")
    assert "no accessible knowledge bases" in _hit_text(result)
