from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.vector_index_service import CHUNKING_VERSION, VectorIndexService


@pytest.mark.asyncio
async def test_replace_file_chunks_uses_batch_embedding():
    file_id = uuid.uuid4()
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    embedder = MagicMock()
    embedder.encode_documents.side_effect = [
        [[0.1, 0.2], [0.3, 0.4]],
        [[0.5, 0.6]],
    ]
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    await service.replace_file_chunks(
        file_id=file_id,
        chunks=["chunk 1", "chunk 2", "chunk 3"],
        filename="demo.txt",
        file_path="/tmp/demo.txt",
    )

    assert embedder.encode_documents.call_count == 2
    embedder.encode_documents.assert_any_call(["chunk 1", "chunk 2"])
    embedder.encode_documents.assert_any_call(["chunk 3"])
    repo.delete_chunks_for_file.assert_awaited_once_with(file_id=file_id)
    repo.add_chunks.assert_awaited_once()

    records = repo.add_chunks.await_args.args[0]
    assert [record["chunk_index"] for record in records] == [0, 1, 2]
    assert [record["embedding"] for record in records] == [
        [0.1, 0.2],
        [0.3, 0.4],
        [0.5, 0.6],
    ]
    assert [record["content_hash"] for record in records] == [
        hashlib.sha256(text.encode("utf-8")).hexdigest()
        for text in ["chunk 1", "chunk 2", "chunk 3"]
    ]
    assert [record["search_text"] for record in records] == [
        "chunk 1",
        "chunk 2",
        "chunk 3",
    ]
    assert {record["chunking_version"] for record in records} == {CHUNKING_VERSION}


@pytest.mark.asyncio
async def test_replace_file_chunks_uses_embedding_content_for_structured_chunks():
    file_id = uuid.uuid4()
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    embedder = MagicMock()
    embedder.encode_documents.return_value = [[0.1, 0.2]]
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    await service.replace_file_chunks(
        file_id=file_id,
        chunks=[
            {
                "content": "原文内容",
                "embedding_content": "[文档: demo.md] [章节: Intro]\n原文内容",
                "meta_info": {"section_path": "Intro"},
            }
        ],
        filename="demo.md",
        file_path="/tmp/demo.md",
    )

    embedder.encode_documents.assert_called_once_with(
        ["[文档: demo.md] [章节: Intro]\n原文内容"]
    )
    records = repo.add_chunks.await_args.args[0]
    assert records[0]["content"] == "原文内容"
    assert records[0]["search_text"].startswith("原文内容")
    assert (
        records[0]["content_hash"]
        == hashlib.sha256(
            "[文档: demo.md] [章节: Intro]\n原文内容".encode()
        ).hexdigest()
    )
    assert records[0]["meta_info"] == {
        "filename": "demo.md",
        "path": "/tmp/demo.md",
        "section_path": "Intro",
    }


@pytest.mark.asyncio
async def test_replace_file_chunks_rejects_mismatched_embedding_count():
    repo = SimpleNamespace(
        delete_chunks_for_file=AsyncMock(),
        add_chunks=AsyncMock(),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    embedder = MagicMock()
    embedder.encode_documents.return_value = [[0.1, 0.2]]
    service = VectorIndexService(
        uow=uow,
        embedder=embedder,
        embed_batch_size=2,
    )

    with pytest.raises(ValueError):
        await service.replace_file_chunks(
            file_id=uuid.uuid4(),
            chunks=["chunk 1", "chunk 2"],
            filename="demo.txt",
            file_path="/tmp/demo.txt",
        )

    repo.delete_chunks_for_file.assert_not_awaited()
    repo.add_chunks.assert_not_awaited()


@pytest.mark.asyncio
async def test_fulltext_search_normalizes_query_before_repository_call():
    kb_id = uuid.uuid4()
    repo = SimpleNamespace(
        search_chunks_for_kb_fulltext=AsyncMock(return_value=[]),
    )
    uow = SimpleNamespace(knowledge_repo=repo)
    service = VectorIndexService(
        uow=uow,
        embedder=MagicMock(),
    )

    result = await service.search_chunks_for_kb_fulltext(
        query_text="数据库 max_connections",
        kb_id=kb_id,
        limit=5,
    )

    assert result == []
    repo.search_chunks_for_kb_fulltext.assert_awaited_once()
    call_kwargs = repo.search_chunks_for_kb_fulltext.await_args.kwargs
    assert call_kwargs["kb_id"] == kb_id
    assert call_kwargs["limit"] == 5
    assert call_kwargs["normalized_query"].startswith("数据库 max_connections")
    assert "query_text" not in call_kwargs
