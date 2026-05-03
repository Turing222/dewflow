from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
)
from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
    StreamGenerationPayload,
)
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat_schema import LLMQueryDTO, LLMResultDTO


class DummyUoW:
    def __init__(self) -> None:
        self.chat_repo = AsyncMock()
        self.user_repo = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.set_calls: list[tuple[str, str, int]] = []
        self.deleted: list[str] = []

    async def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    async def set(self, key: str, value: str, ex: int) -> None:
        self.set_calls.append((key, value, ex))

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


class StreamingLLM:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(
        self,
        chunks: list[str],
        error: Exception | None = None,
        rerank_content: str | None = None,
    ) -> None:
        self.chunks = chunks
        self.error = error
        self.stream_queries: list[LLMQueryDTO] = []
        self.generate_response = AsyncMock(
            return_value=LLMResultDTO(
                content=rerank_content
                or '{"rankings": [{"index": 1, "score": 10}]}',
            )
        )

    async def stream_response(self, query: LLMQueryDTO) -> AsyncIterator[str]:
        self.stream_queries.append(query)
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error


@pytest.mark.asyncio
async def test_worker_generation_persists_success_and_publishes_done(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    uow = DummyUoW()
    assistant_message_id = uuid.uuid4()
    user_id = uuid.uuid4()
    updated_message = object()
    uow.chat_repo.update_message_status.return_value = updated_message
    uow.user_repo.increment_used_tokens_guarded.return_value = True

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=StreamingLLM(["hello", " world"]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 7)

    await workflow.generate_stream(
        payload=StreamGenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        idempotency_lock_key="idempotency:test",
    )

    assert redis.published == [
        ("stream:test", encode_chunk_event("hello")),
        ("stream:test", encode_chunk_event(" world")),
        ("stream:test", encode_done_event()),
    ]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "hello world"
    assert isinstance(update_kwargs["tokens_input"], int)
    assert update_kwargs["tokens_output"] == 7
    total_tokens = update_kwargs["tokens_input"] + 7
    uow.user_repo.increment_used_tokens_guarded.assert_awaited_once_with(
        user_id,
        total_tokens,
    )
    assert redis.set_calls == [("idempotency:test", str(assistant_message_id), 3600)]


@pytest.mark.asyncio
async def test_worker_generation_marks_failed_and_publishes_error(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    uow = DummyUoW()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()

    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=StreamingLLM(
            [],
            error=app_service_error("provider failed", code="LLM_FAILED"),
        ),
    )

    await workflow.generate_stream(
        payload=StreamGenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:test",
    )

    assert redis.published == [
        ("stream:test", encode_error_event("provider failed")),
        ("stream:test", encode_done_event()),
    ]
    assert redis.deleted == ["idempotency:test"]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "provider failed"


@pytest.mark.asyncio
async def test_worker_generation_reranks_candidates_when_enabled(
    monkeypatch,
):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.settings.RAG_RERANK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.settings.RAG_RERANK_TOP_K",
        1,
    )

    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(
        ["answer"],
        rerank_content='{"rankings": [{"index": 2, "score": 9}]}',
    )
    workflow = LLMGenerationWorkerWorkflow(uow=uow, llm_service=llm_service)

    await workflow.generate_stream(
        payload=StreamGenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
            kb_id=uuid.uuid4(),
            rag_candidates=[
                {
                    "id": str(uuid.uuid4()),
                    "content": "low",
                    "source_type": "file",
                    "file_id": str(uuid.uuid4()),
                    "message_id": None,
                    "filename": "a.md",
                    "chunk_index": 0,
                    "meta_info": {},
                    "distance": 0.3,
                    "score": 0.7,
                },
                {
                    "id": str(uuid.uuid4()),
                    "content": "high",
                    "source_type": "file",
                    "file_id": str(uuid.uuid4()),
                    "message_id": None,
                    "filename": "b.md",
                    "chunk_index": 1,
                    "meta_info": {},
                    "distance": 0.1,
                    "score": 0.9,
                },
            ],
        ),
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
    )

    llm_service.generate_response.assert_awaited_once()
    stream_query = llm_service.stream_queries[0]
    system_message = stream_query.conversation_history[0]
    assert "high" in system_message["content"]
    assert "low" not in system_message["content"]
