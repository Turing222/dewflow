"""Unit tests for WorkerRAGOrchestrator — RAG plan, retrieval, rerank, and fusion."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rag_planning_service import RAGExecutionPlan

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_rag_hit(index: int = 0) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "content": f"chunk-{index}",
        "source_type": "file",
        "file_id": str(uuid.uuid4()),
        "message_id": None,
        "filename": f"doc-{index}.md",
        "chunk_index": index,
        "meta_info": {},
        "distance": 0.1 + index * 0.1,
        "score": 0.9 - index * 0.1,
    }


# ── Test 1: prepare_context with kb_id=None and empty retrieval → no refusal ──


@pytest.mark.asyncio
async def test_prepare_context_kb_id_none_empty_retrieval_no_refusal(monkeypatch):
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.config.ai_settings.ai_settings.RAG_RERANK_ENABLED",
        False,
    )
    monkeypatch.setattr(
        "backend.config.ai_settings.ai_settings.RAG_PLANNER_ENABLED",
        False,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        conversation_history=[],
    )
    # kb_id is None by default

    rag_service = MagicMock()
    rag_service.retrieve_fulltext = AsyncMock(return_value=[])
    rag_service.retrieve = AsyncMock(return_value=[])

    mock_assembled_prompt = SimpleNamespace(total_tokens=42, messages=[])
    mock_context_builder = MagicMock()
    mock_context_builder.build_from_chunks.return_value = SimpleNamespace(
        assembled_prompt=mock_assembled_prompt,
        search_context={"key": "val"},
    )

    orchestrator = WorkerRAGOrchestrator(
        rag_service=rag_service,
        chat_context_builder=mock_context_builder,
    )

    result = await orchestrator.prepare_context(payload)

    assert result.refusal_decision is None
    assert result.assembled_prompt is not None


# ── Test 2: build_rag_plan planner throws → default fallback ──────────────────


@pytest.mark.asyncio
async def test_build_rag_plan_planner_error_falls_back_to_default(monkeypatch):
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.config.ai_settings.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.config.ai_settings.ai_settings.RAG_RERANK_ENABLED",
        False,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test query",
        kb_id=uuid.uuid4(),
        conversation_history=[],
    )

    planner = MagicMock()
    planner.plan = AsyncMock(side_effect=ValueError("LLM API failed"))

    orchestrator = WorkerRAGOrchestrator(
        rag_planning_service=planner,
    )

    plan, planner_used = await orchestrator.build_rag_plan(payload)

    assert isinstance(plan, RAGExecutionPlan)
    assert plan.should_use_rag is True
    assert planner_used is False


# ── Test 3: retrieve_rag_candidates connection error → empty list ──────────────


@pytest.mark.asyncio
async def test_retrieve_rag_candidates_connection_error_returns_empty(monkeypatch):
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    monkeypatch.setattr(
        "backend.config.ai_settings.ai_settings.RAG_RERANK_ENABLED",
        False,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        kb_id=uuid.uuid4(),
        conversation_history=[],
    )

    rag_service = MagicMock()
    rag_service.retrieve = AsyncMock(side_effect=ConnectionError("DB down"))

    rag_plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="vector",
        top_k=4,
    )

    orchestrator = WorkerRAGOrchestrator(rag_service=rag_service)
    result = await orchestrator.retrieve_rag_candidates(payload, rag_plan)

    assert result == []
    rag_service.retrieve.assert_awaited_once()


# ── Test 4: rerank error → fallback to original candidates[:limit] ─────────────


@pytest.mark.asyncio
async def test_rerank_candidates_if_enabled_rerank_error_falls_back(monkeypatch):
    from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
    from backend.models.schemas.chat.payloads import GenerationPayload

    # Patch concurrency slot to avoid actual slot acquisition.
    calls: list[dict] = []

    class _FakeSlot:
        def __init__(self, attrs):
            self.attrs = attrs

        async def __aenter__(self):
            calls.append(self.attrs)

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        "backend.application.chat.worker_rag_orchestrator.llm_concurrency_slot",
        _FakeSlot,
    )

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="test",
        conversation_history=[],
    )

    candidates = [_make_rag_hit(i) for i in range(3)]

    rag_plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="vector",
        top_k=4,
        use_rerank=True,
        rerank_top_k=2,
        candidate_count=20,
    )

    rag_service = MagicMock()
    rag_service.rerank = AsyncMock(side_effect=RuntimeError("rerank failed"))

    orchestrator = WorkerRAGOrchestrator(rag_service=rag_service)
    result = await orchestrator.rerank_candidates_if_enabled(
        payload, candidates, rag_plan
    )

    assert len(result) == 2
    assert result[0]["content"] == "chunk-0"
    assert result[1]["content"] == "chunk-1"


# ── Test 5: _fuse_hybrid_hits with only vector hits ──────────────────────────


def test_fuse_hybrid_hits_only_vector_hits():
    from backend.services.vector_index_service import VectorIndexService

    chunk_a = MagicMock()
    chunk_a.id = uuid.uuid4()
    chunk_b = MagicMock()
    chunk_b.id = uuid.uuid4()

    vector_hits = [(chunk_a, 0.1), (chunk_b, 0.3)]
    fulltext_hits: list = []

    result = VectorIndexService._fuse_hybrid_hits(
        vector_hits=vector_hits,
        fulltext_hits=fulltext_hits,
        limit=10,
        vector_weight=0.7,
        fulltext_weight=0.3,
    )

    assert len(result) == 2
    # chunk_a was rank 1 (0.1 distance), chunk_b rank 2 (0.3 distance).
    # RRF: chunk_a gets higher score → lower distance when normalized.
    assert result[0][0].id == chunk_a.id
    assert result[1][0].id == chunk_b.id
