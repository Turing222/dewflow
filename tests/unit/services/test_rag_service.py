import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rag_service import RAGService


def _build_service(llm_service=None) -> RAGService:
    return RAGService(
        embedder=MagicMock(),
        vector_index_service=MagicMock(),
        top_k=4,
        llm_service=llm_service,
        rerank_candidate_count=3,
        rerank_top_k=2,
    )


def _chunk(content: str, index: int):
    return SimpleNamespace(
        id=uuid.uuid4(),
        content=content,
        source_type="file",
        file_id=uuid.uuid4(),
        message_id=None,
        file=SimpleNamespace(filename="source.md"),
        chunk_index=index,
        meta_info={},
    )


@pytest.mark.asyncio
async def test_retrieve_fulltext_formats_hits():
    service = _build_service()
    kb_id = uuid.uuid4()
    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        content="chunk text",
        source_type="file",
        file_id=uuid.uuid4(),
        message_id=None,
        file=SimpleNamespace(filename="source.md"),
        chunk_index=7,
        meta_info={"page_label": "3"},
    )
    service.vector_index_service.search_chunks_for_kb_fulltext = AsyncMock(
        return_value=[(chunk, 0.2)]
    )

    result = await service.retrieve_fulltext(
        query_text="test query",
        kb_id=kb_id,
    )

    assert len(result) == 1
    assert result[0]["id"] == str(chunk.id)
    assert result[0]["content"] == "chunk text"
    assert result[0]["source_type"] == "file"
    assert result[0]["file_id"] == str(chunk.file_id)
    assert result[0]["filename"] == "source.md"
    assert result[0]["chunk_index"] == 7
    assert result[0]["meta_info"] == {"page_label": "3"}
    assert result[0]["distance"] == 0.2
    assert result[0]["score"] == 0.8


@pytest.mark.asyncio
async def test_retrieve_hybrid_returns_empty_on_error():
    service = _build_service()
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        side_effect=RuntimeError("db error")
    )

    result = await service.retrieve_hybrid(
        query_text="test query",
        kb_id=uuid.uuid4(),
        top_k=3,
    )

    assert result == []


@pytest.mark.asyncio
async def test_retrieve_with_rerank_orders_by_llm_scores():
    llm_service = SimpleNamespace(
        generate_response=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                content='{"rankings": [{"index": 2, "score": 9}, {"index": 1, "score": 3}]}',
                error_message=None,
            )
        )
    )
    service = _build_service(llm_service=llm_service)
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["beta", "alpha"]
    assert result[0]["rerank_score"] == 9
    llm_service.generate_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_retrieve_with_rerank_falls_back_to_candidate_order_on_bad_json():
    llm_service = SimpleNamespace(
        generate_response=AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                content="not json",
                error_message=None,
            )
        )
    )
    service = _build_service(llm_service=llm_service)
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_retrieve_with_rerank_without_llm_returns_candidate_order():
    service = _build_service(llm_service=None)
    candidates = [_chunk("alpha", 0), _chunk("beta", 1), _chunk("gamma", 2)]
    service.vector_index_service.search_chunks_for_kb_hybrid = AsyncMock(
        return_value=[(chunk, 0.1) for chunk in candidates]
    )

    result = await service.retrieve_with_rerank(
        query_text="query",
        kb_id=uuid.uuid4(),
    )

    assert [chunk["content"] for chunk in result] == ["alpha", "beta"]
