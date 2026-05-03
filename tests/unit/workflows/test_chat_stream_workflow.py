import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.application.chat.web_stream_workflow import ChatWorkflow


@pytest.mark.asyncio
async def test_stream_workflow_defers_rerank_to_worker(monkeypatch):
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(return_value=[]),
        retrieve_hybrid=AsyncMock(return_value=[{"content": "candidate"}]),
        retrieve_with_rerank=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "backend.application.chat.web_stream_workflow.settings.RAG_RERANK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.application.chat.web_stream_workflow.settings.RAG_RERANK_CANDIDATE_COUNT",
        8,
    )

    workflow = ChatWorkflow(
        uow=SimpleNamespace(),
        llm_service=SimpleNamespace(),
        rag_service=rag_service,
    )
    result = await workflow._retrieve_rag_candidates_for_worker(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert result == [{"content": "candidate"}]
    rag_service.retrieve_hybrid.assert_awaited_once()
    rag_service.retrieve.assert_not_awaited()
    rag_service.retrieve_with_rerank.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_workflow_uses_plain_retrieve_without_rerank(monkeypatch):
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(return_value=[{"content": "hit"}]),
        retrieve_hybrid=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "backend.application.chat.web_stream_workflow.settings.RAG_RERANK_ENABLED",
        False,
    )

    workflow = ChatWorkflow(
        uow=SimpleNamespace(),
        llm_service=SimpleNamespace(),
        rag_service=rag_service,
    )
    result = await workflow._retrieve_rag_candidates_for_worker(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert result == [{"content": "hit"}]
    rag_service.retrieve.assert_awaited_once()
    rag_service.retrieve_hybrid.assert_not_awaited()
