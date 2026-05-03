from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.ai.core.chat_context_builder import ChatContextBuilder


@pytest.mark.asyncio
async def test_build_uses_rag_prompt_and_search_context_when_chunks_found():
    kb_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    chunk_id_2 = uuid.uuid4()
    file_id = uuid.uuid4()
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(
            return_value=[
                {
                    "id": str(chunk_id),
                    "content": "索引里的事实: Codex smoke RAG 正常。",
                    "source_type": "file",
                    "file_id": str(file_id),
                    "message_id": None,
                    "filename": "smoke.txt",
                    "chunk_index": 3,
                    "meta_info": {"page_label": "1", "section_path": "Guide / Setup"},
                    "distance": 0.2,
                    "score": 0.8,
                },
                {
                    "id": str(chunk_id_2),
                    "content": "第二段索引事实。",
                    "source_type": "file",
                    "file_id": str(file_id),
                    "message_id": None,
                    "filename": "smoke.txt",
                    "chunk_index": 4,
                    "meta_info": {"page_label": "2"},
                    "distance": 0.3,
                    "score": 0.7,
                },
            ]
        )
    )
    builder = ChatContextBuilder(rag_service=rag_service)
    history_messages = [
        SimpleNamespace(role="user", content="上一轮问题"),
        SimpleNamespace(role="assistant", content="上一轮回答"),
        SimpleNamespace(role="user", content="本轮问题"),
    ]

    result = await builder.build(
        history_messages=history_messages,
        current_query="本轮问题",
        kb_id=kb_id,
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="本轮问题",
        kb_id=kb_id,
    )
    system_message = result.assembled_prompt.messages[0]
    assert system_message["role"] == "system"
    assert "--- 参考资料 ---" in system_message["content"]
    assert "[R1.1]" in system_message["content"]
    assert "[R1.2]" in system_message["content"]
    assert "smoke.txt" in system_message["content"]
    assert "章节：Guide / Setup" in system_message["content"]
    assert "索引里的事实" in system_message["content"]
    assert result.assembled_prompt.messages[-1] == {
        "role": "user",
        "content": "本轮问题",
    }
    assert {
        "role": "user",
        "content": "本轮问题",
    } not in result.assembled_prompt.messages[:-1]
    assert result.search_context is not None
    assert result.search_context["version"] == 1
    assert result.search_context["kb_id"] == str(kb_id)
    assert result.search_context["query"] == "本轮问题"
    assert result.search_context["retrieval"] == {
        "hit_count": 2,
        "source_count": 1,
        "max_score": 0.8,
        "avg_score": 0.75,
    }
    assert result.search_context["refs"][0]["ref_id"] == "R1"
    assert result.search_context["refs"][0]["filename"] == "smoke.txt"
    assert result.search_context["refs"][0]["chunks"][0] == {
        "ref_id": "R1.1",
        "chunk_id": str(chunk_id),
        "chunk_index": 3,
        "score": 0.8,
        "distance": 0.2,
        "meta_info": {"page_label": "1", "section_path": "Guide / Setup"},
    }
    assert result.search_context["refs"][0]["chunks"][1]["ref_id"] == "R1.2"
    assert result.search_context["refs"][0]["chunks"][1]["chunk_id"] == str(chunk_id_2)
    assert result.search_context["chunks"][0]["ref_id"] == "R1.1"
    assert result.search_context["chunks"][0]["id"] == str(chunk_id)
    assert result.search_context["chunks"][0]["chunk_index"] == 3


@pytest.mark.asyncio
async def test_build_falls_back_to_plain_prompt_without_rag_chunks():
    kb_id = uuid.uuid4()
    rag_service = SimpleNamespace(retrieve=AsyncMock(return_value=[]))
    builder = ChatContextBuilder(rag_service=rag_service)

    result = await builder.build(
        history_messages=[],
        current_query="普通问题",
        kb_id=kb_id,
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="普通问题",
        kb_id=kb_id,
    )
    system_message = result.assembled_prompt.messages[0]
    assert "--- 参考资料 ---" not in system_message["content"]
    assert result.search_context is None


@pytest.mark.asyncio
async def test_build_falls_back_to_plain_prompt_when_rag_errors():
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(side_effect=RuntimeError("vector db down"))
    )
    builder = ChatContextBuilder(rag_service=rag_service)

    result = await builder.build(
        history_messages=[],
        current_query="降级问题",
        kb_id=uuid.uuid4(),
    )

    assert result.search_context is None
    assert "--- 参考资料 ---" not in result.assembled_prompt.messages[0]["content"]


@pytest.mark.asyncio
async def test_build_uses_rerank_when_enabled(monkeypatch):
    kb_id = uuid.uuid4()
    rag_service = SimpleNamespace(
        retrieve=AsyncMock(return_value=[]),
        retrieve_with_rerank=AsyncMock(
            return_value=[
                {
                    "id": str(uuid.uuid4()),
                    "content": "reranked fact",
                    "source_type": "file",
                    "file_id": str(uuid.uuid4()),
                    "message_id": None,
                    "filename": "source.md",
                    "chunk_index": 0,
                    "meta_info": {},
                    "distance": 0.1,
                    "score": 0.9,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "backend.ai.core.chat_context_builder.settings.RAG_RERANK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.ai.core.chat_context_builder.settings.RAG_RERANK_TOP_K",
        2,
    )
    monkeypatch.setattr(
        "backend.ai.core.chat_context_builder.settings.RAG_RERANK_CANDIDATE_COUNT",
        8,
    )

    builder = ChatContextBuilder(rag_service=rag_service)
    await builder.build(
        history_messages=[],
        current_query="本轮问题",
        kb_id=kb_id,
    )

    rag_service.retrieve.assert_not_awaited()
    rag_service.retrieve_with_rerank.assert_awaited_once_with(
        query_text="本轮问题",
        kb_id=kb_id,
        top_k=2,
        candidate_count=8,
    )


def test_build_from_chunks_does_not_call_rag_service():
    kb_id = uuid.uuid4()
    rag_service = SimpleNamespace(retrieve=AsyncMock(return_value=[]))
    builder = ChatContextBuilder(rag_service=rag_service)

    result = builder.build_from_chunks(
        history_messages=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "回答"},
            {"role": "user", "content": "本轮问题"},
        ],
        current_query="本轮问题",
        kb_id=kb_id,
        rag_chunks=[
            {
                "id": str(uuid.uuid4()),
                "content": "worker provided fact",
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "source.md",
                "chunk_index": 0,
                "meta_info": {},
                "distance": 0.1,
                "score": 0.9,
            }
        ],
    )

    rag_service.retrieve.assert_not_awaited()
    assert result.search_context is not None
    assert "worker provided fact" in result.assembled_prompt.messages[0]["content"]
