from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jinja2 import Template

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.ai.core.context_budgeter import ContextBudgeter
from backend.ai.core.live_window_builder import LiveWindowBuilder
from backend.ai.core.prompt_manager import PromptManager
from backend.core.exceptions import AppException
from backend.models.schemas.chat.context_state import ContextState


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


def test_build_from_chunks_injects_context_state_into_plain_prompt():
    builder = ChatContextBuilder()

    result = builder.build_from_chunks(
        history_messages=[],
        current_query="继续",
        kb_id=None,
        rag_chunks=[],
        context_state=ContextState(
            decisions=["数据库使用 PostgreSQL"],
            constraints=["回答必须使用中文"],
            preferences=["偏好要点式总结"],
        ),
    )

    system_content = result.assembled_prompt.messages[0]["content"]
    assert "--- 当前对话状态 ---" in system_content
    assert "已确认决策" in system_content
    assert "数据库使用 PostgreSQL" in system_content
    assert "用户要求" in system_content
    assert "回答必须使用中文" in system_content
    assert "用户偏好" in system_content
    assert "偏好要点式总结" in system_content


def test_build_from_chunks_omits_empty_context_state_block():
    builder = ChatContextBuilder()

    result = builder.build_from_chunks(
        history_messages=[],
        current_query="继续",
        kb_id=None,
        rag_chunks=[],
        context_state=ContextState(),
    )

    assert "--- 当前对话状态 ---" not in result.assembled_prompt.messages[0]["content"]


def test_build_from_chunks_keeps_context_state_separate_from_rag_chunks():
    builder = ChatContextBuilder()

    result = builder.build_from_chunks(
        history_messages=[],
        current_query="解释方案",
        kb_id=uuid.uuid4(),
        context_state=ContextState(decisions=["本轮使用轻量记忆"]),
        rag_chunks=[
            {
                "id": str(uuid.uuid4()),
                "content": "RAG evidence",
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

    system_content = result.assembled_prompt.messages[0]["content"]
    assert "--- 当前对话状态 ---" in system_content
    assert "--- 参考资料 ---" in system_content
    assert "本轮使用轻量记忆" in system_content
    assert "RAG evidence" in system_content


def test_build_from_chunks_trims_rag_chunks_to_budget():
    retained_content = "A" * 20
    builder = ChatContextBuilder(
        rag_prompt_manager=PromptManager(
            system_template=Template("{{ context_chunks|join('\\n') }}"),
            max_context_tokens=340,
            reserved_response_tokens=80,
            model_name="gpt-4",
        ),
        context_budgeter=ContextBudgeter(
            max_context_tokens=340,
            reserved_response_tokens=80,
            model_name="gpt-4",
        ),
        live_window_builder=LiveWindowBuilder(recent_rounds=1),
    )

    result = builder.build_from_chunks(
        history_messages=[],
        current_query="问题",
        kb_id=uuid.uuid4(),
        rag_chunks=[
            {
                "id": str(uuid.uuid4()),
                "content": retained_content,
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "one.md",
                "chunk_index": 0,
                "meta_info": {},
                "distance": 0.1,
                "score": 0.9,
            },
            {
                "id": str(uuid.uuid4()),
                "content": "B" * 8000,
                "source_type": "file",
                "file_id": str(uuid.uuid4()),
                "message_id": None,
                "filename": "two.md",
                "chunk_index": 1,
                "meta_info": {},
                "distance": 0.2,
                "score": 0.8,
            },
        ],
    )

    assert result.assembled_prompt.total_tokens <= builder.context_budgeter.total_budget
    assert retained_content in result.assembled_prompt.messages[0]["content"]
    assert len(result.assembled_prompt.messages[0]["content"]) < 8000


def test_build_from_chunks_raises_when_final_context_exceeds_budget():
    builder = ChatContextBuilder(
        prompt_manager=PromptManager(
            system_template=Template("S" * 2000),
            max_context_tokens=80,
            reserved_response_tokens=20,
            model_name="gpt-4",
        ),
        context_budgeter=ContextBudgeter(
            max_context_tokens=80,
            reserved_response_tokens=20,
            model_name="gpt-4",
        ),
        live_window_builder=LiveWindowBuilder(recent_rounds=1),
    )

    with pytest.raises(AppException) as exc_info:
        builder.build_from_chunks(
            history_messages=[],
            current_query="问题",
            kb_id=None,
            rag_chunks=[],
        )

    assert exc_info.value.code == "TOKEN_LIMIT_EXCEEDED"
    assert exc_info.value.status_code == 413
