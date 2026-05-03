from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from backend.application.chat.worker_generation_workflow import (
    LLMGenerationWorkerWorkflow,
)
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat_schema import LLMQueryDTO


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

    def __init__(self, chunks: list[str], error: Exception | None = None) -> None:
        self.chunks = chunks
        self.error = error

    async def stream_response(self, query: LLMQueryDTO) -> AsyncIterator[str]:
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
        llm_query=LLMQueryDTO(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        tokens_input=5,
        search_context={"chunks": []},
        idempotency_lock_key="idempotency:test",
    )

    assert redis.published == [
        ("stream:test", "hello"),
        ("stream:test", " world"),
        ("stream:test", "[DONE]"),
    ]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "hello world"
    assert update_kwargs["tokens_input"] == 5
    assert update_kwargs["tokens_output"] == 7
    uow.user_repo.increment_used_tokens_guarded.assert_awaited_once_with(user_id, 12)
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
        llm_query=LLMQueryDTO(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:test",
    )

    assert redis.published == [
        ("stream:test", "[ERROR]provider failed"),
        ("stream:test", "[DONE]"),
    ]
    assert redis.deleted == ["idempotency:test"]
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "provider failed"

