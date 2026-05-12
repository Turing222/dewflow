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
)
from backend.core.exceptions import app_service_error
from backend.models.schemas.chat.dto import LLMQueryDTO, LLMResultDTO
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.services.rag_planning_service import RAGExecutionPlan


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


class RecordingConcurrencySlot:
    def __init__(self, calls: list[dict], attributes: dict | None) -> None:
        self.calls = calls
        self.attributes = attributes or {}

    async def __aenter__(self) -> None:
        self.calls.append(self.attributes)

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def install_llm_slot_recorder(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_llm_concurrency_slot(attributes: dict | None = None):
        return RecordingConcurrencySlot(calls, attributes)

    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.llm_concurrency_slot",
        fake_llm_concurrency_slot,
    )
    return calls


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
                content=rerank_content or '{"rankings": [{"index": 1, "score": 10}]}',
            )
        )

    async def stream_response(self, query: LLMQueryDTO) -> AsyncIterator[str]:
        self.stream_queries.append(query)
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error


class NonStreamingLLM:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, result: LLMResultDTO) -> None:
        self.generate_response = AsyncMock(return_value=result)

    async def stream_response(self, query: LLMQueryDTO) -> AsyncIterator[str]:
        if False:
            yield query.query_text


class RecordingRAGService:
    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.uow = None
        self.retrieve = AsyncMock(return_value=hits)
        self.retrieve_fulltext = AsyncMock(return_value=hits)
        self.retrieve_hybrid = AsyncMock(return_value=hits)


class RecordingRAGPlanner:
    def __init__(
        self,
        plan: RAGExecutionPlan | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response_plan = plan
        self.error = error
        self.plan_calls: list[dict] = []

    async def plan(self, **kwargs) -> RAGExecutionPlan:
        self.plan_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response_plan is not None
        return self.response_plan


def make_rag_hit(content: str = "worker-side context") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "source_type": "file",
        "file_id": str(uuid.uuid4()),
        "message_id": None,
        "filename": "ctx.md",
        "chunk_index": 0,
        "meta_info": {},
        "distance": 0.1,
        "score": 0.9,
    }


@pytest.mark.asyncio
async def test_worker_generation_persists_success_and_publishes_done(monkeypatch):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
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

    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )

    await workflow.generate_stream(
        payload=payload,
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
    assert slot_calls == [
        {
            "chat.session_id": payload.session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.stream": True,
        }
    ]


@pytest.mark.asyncio
async def test_worker_generation_marks_failed_and_publishes_error(monkeypatch):
    redis = FakeRedis()
    install_llm_slot_recorder(monkeypatch)
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
        payload=GenerationPayload(
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
async def test_worker_nonstream_generation_uses_llm_slot_and_persists_success(
    monkeypatch,
):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    uow = DummyUoW()
    assistant_message_id = uuid.uuid4()
    user_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    uow.user_repo.increment_used_tokens_guarded.return_value = True
    llm_service = NonStreamingLLM(
        LLMResultDTO(content="full answer", completion_tokens=5, latency_ms=12)
    )
    workflow = LLMGenerationWorkerWorkflow(uow=uow, llm_service=llm_service)
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_message_id,
        user_id=user_id,
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "full answer"
    llm_service.generate_response.assert_awaited_once()
    uow.chat_repo.update_message_status.assert_awaited_once()
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["message_id"] == assistant_message_id
    assert update_kwargs["content"] == "full answer"
    assert update_kwargs["tokens_output"] == 5
    total_tokens = update_kwargs["tokens_input"] + 5
    uow.user_repo.increment_used_tokens_guarded.assert_awaited_once_with(
        user_id,
        total_tokens,
    )
    assert redis.set_calls == [("idempotency:test", str(assistant_message_id), 3600)]
    assert slot_calls == [
        {
            "chat.session_id": payload.session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.stream": False,
        }
    ]


@pytest.mark.asyncio
async def test_worker_nonstream_refuses_when_rag_has_no_hits(monkeypatch):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    uow = DummyUoW()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = NonStreamingLLM(LLMResultDTO(content="should not run"))
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=RecordingRAGService([]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="知识库里有什么？",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    result = await workflow.generate_nonstream(
        payload=payload,
        assistant_message_id=assistant_message_id,
        idempotency_lock_key="idempotency:test",
    )

    assert result.success is True
    assert result.content == "知识库中没有找到足够相关的信息，暂时无法基于资料回答。"
    llm_service.generate_response.assert_not_awaited()
    assert slot_calls == []
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["status"].value == "success"
    assert update_kwargs["content"] == result.content
    assert update_kwargs["search_context"]["rag_refusal"] is True
    assert update_kwargs["search_context"]["reason"] == "RAG 命中数量不足"
    assert redis.set_calls == [("idempotency:test", str(assistant_message_id), 3600)]


@pytest.mark.asyncio
async def test_worker_stream_refuses_when_rag_has_no_hits(monkeypatch):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    uow = DummyUoW()
    assistant_message_id = uuid.uuid4()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(["should not stream"])
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=RecordingRAGService([]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="知识库里有什么？",
            conversation_history=[],
            kb_id=uuid.uuid4(),
        ),
        channel="stream:test",
        assistant_message_id=assistant_message_id,
    )

    refusal = "知识库中没有找到足够相关的信息，暂时无法基于资料回答。"
    assert redis.published == [
        ("stream:test", encode_chunk_event(refusal)),
        ("stream:test", encode_done_event()),
    ]
    assert llm_service.stream_queries == []
    assert slot_calls == []
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["content"] == refusal
    assert update_kwargs["search_context"]["rag_refusal"] is True


@pytest.mark.asyncio
async def test_worker_generation_retrieves_rag_candidates_when_kb_id_exists(
    monkeypatch,
):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_RERANK_ENABLED",
        False,
    )

    rag_hit = {
        "id": str(uuid.uuid4()),
        "content": "worker-side context",
        "source_type": "file",
        "file_id": str(uuid.uuid4()),
        "message_id": None,
        "filename": "ctx.md",
        "chunk_index": 0,
        "meta_info": {},
        "distance": 0.1,
        "score": 0.9,
    }
    rag_service = RecordingRAGService([rag_hit])
    llm_service = NonStreamingLLM(LLMResultDTO(content="answer"))
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=rag_service,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=4,
    )
    rag_service.retrieve_hybrid.assert_not_awaited()
    query = llm_service.generate_response.call_args.args[0]
    assert "worker-side context" in query.conversation_history[0]["content"]


@pytest.mark.asyncio
async def test_worker_generation_refuses_low_vector_score(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    low_hit = make_rag_hit("weak context")
    low_hit["score"] = 0.1
    low_hit["distance"] = 0.9
    llm_service = NonStreamingLLM(LLMResultDTO(content="should not run"))
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=RecordingRAGService([low_hit]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="弱相关问题",
            conversation_history=[],
            kb_id=uuid.uuid4(),
        ),
        assistant_message_id=uuid.uuid4(),
    )

    assert result.success is True
    llm_service.generate_response.assert_not_awaited()
    assert result.search_context is not None
    assert result.search_context["reason"] == "RAG 相关性分数不足"
    assert result.search_context["best_score"] == 0.1


@pytest.mark.asyncio
async def test_worker_generation_keeps_old_behavior_when_refusal_disabled(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_REFUSAL_ENABLED",
        False,
    )

    llm_service = NonStreamingLLM(LLMResultDTO(content="fallback answer"))
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=RecordingRAGService([]),
    )

    result = await workflow.generate_nonstream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="知识库里有什么？",
            conversation_history=[],
            kb_id=uuid.uuid4(),
        ),
        assistant_message_id=uuid.uuid4(),
    )

    assert result.content == "fallback answer"
    llm_service.generate_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_generation_skips_rag_when_planner_declines(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=False,
            retrieval_mode="vector",
            top_k=4,
            reason="无需知识库",
        )
    )
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    assert len(planner.plan_calls) == 1
    rag_service.retrieve.assert_not_awaited()
    rag_service.retrieve_fulltext.assert_not_awaited()
    rag_service.retrieve_hybrid.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_generation_does_not_plan_without_kb(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(error=AssertionError("planner should not run"))
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=None,
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    assert planner.plan_calls == []
    rag_service.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_generation_skips_planner_when_candidates_exist(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )

    planner = RecordingRAGPlanner(error=AssertionError("planner should not run"))
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=RecordingRAGService([]),
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
        rag_candidates=[make_rag_hit("preloaded context")],
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    assert planner.plan_calls == []


@pytest.mark.asyncio
async def test_worker_generation_uses_fulltext_plan(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )

    rag_service = RecordingRAGService([make_rag_hit("fulltext context")])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=True,
            retrieval_mode="fulltext",
            top_k=2,
            reason="关键词检索",
        )
    )
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="找 ctx.md",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve_fulltext.assert_awaited_once_with(
        query_text="找 ctx.md",
        kb_id=payload.kb_id,
        top_k=2,
    )
    rag_service.retrieve.assert_not_awaited()
    rag_service.retrieve_hybrid.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_generation_reranks_candidates_when_enabled(
    monkeypatch,
):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_RERANK_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_RERANK_TOP_K",
        1,
    )

    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(
        ["answer"],
        rerank_content='{"rankings": [{"index": 2, "score": 9}]}',
    )
    workflow = LLMGenerationWorkerWorkflow(uow=uow, llm_service=llm_service)
    payload = GenerationPayload(
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
    )
    assistant_message_id = uuid.uuid4()

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=assistant_message_id,
    )

    llm_service.generate_response.assert_awaited_once()
    stream_query = llm_service.stream_queries[0]
    system_message = stream_query.conversation_history[0]
    assert "high" in system_message["content"]
    # "a.md" 是 "low" 内容 chunk 的来源文件，rerank 后应被过滤
    assert "a.md" not in system_message["content"]
    assert slot_calls == [
        {
            "chat.session_id": payload.session_id,
            "rag.kb_id": payload.kb_id,
            "rag.rerank": True,
        },
        {
            "chat.session_id": payload.session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.stream": True,
        },
    ]


@pytest.mark.asyncio
async def test_worker_generation_refuses_low_rerank_score(monkeypatch):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_RERANK_ENABLED",
        True,
    )

    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    llm_service = StreamingLLM(
        ["should not stream"],
        rerank_content='{"rankings": [{"index": 1, "score": 2}]}',
    )
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=RecordingRAGService([make_rag_hit("weak rerank context")]),
    )
    monkeypatch.setattr(workflow, "_count_output_tokens", lambda content: 3)

    await workflow.generate_stream(
        payload=GenerationPayload(
            session_id=uuid.uuid4(),
            query_text="hi",
            conversation_history=[],
            kb_id=uuid.uuid4(),
        ),
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
    )

    assert llm_service.generate_response.await_count == 1
    assert llm_service.stream_queries == []
    assert "chat.stream" not in slot_calls[-1]
    update_kwargs = uow.chat_repo.update_message_status.call_args.kwargs
    assert update_kwargs["search_context"]["reason"] == "RAG rerank 相关性不足"
    assert update_kwargs["search_context"]["best_rerank_score"] == 2.0


@pytest.mark.asyncio
async def test_worker_generation_uses_hybrid_rerank_plan(monkeypatch):
    redis = FakeRedis()
    slot_calls = install_llm_slot_recorder(monkeypatch)
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )

    rag_service = RecordingRAGService([make_rag_hit("low"), make_rag_hit("high")])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan(
            should_use_rag=True,
            retrieval_mode="hybrid",
            top_k=2,
            use_rerank=True,
            candidate_count=8,
            rerank_top_k=1,
            reason="需要精选",
        )
    )
    llm_service = StreamingLLM(
        ["answer"],
        rerank_content='{"rankings": [{"index": 2, "score": 9}]}',
    )
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=llm_service,
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    await workflow.generate_stream(
        payload=payload,
        channel="stream:test",
        assistant_message_id=uuid.uuid4(),
    )

    rag_service.retrieve_hybrid.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=8,
    )
    assert llm_service.generate_response.await_count == 1
    assert "rag.rerank" in slot_calls[0]


@pytest.mark.asyncio
async def test_worker_generation_uses_planner_fallback_plan(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_RERANK_ENABLED",
        False,
    )

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        RAGExecutionPlan.from_settings(
            has_kb=True,
            query_text="hi",
            reason="RAG planner 降级为默认计划",
        )
    )
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=4,
    )


@pytest.mark.asyncio
async def test_worker_generation_uses_planner_fallback_on_exception(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.redis_client.init",
        AsyncMock(return_value=redis),
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.application.chat.worker_generation_workflow.ai_settings.RAG_RERANK_ENABLED",
        False,
    )

    rag_service = RecordingRAGService([make_rag_hit()])
    planner = RecordingRAGPlanner(
        error=ValueError("LLM API failed")
    )
    uow = DummyUoW()
    uow.chat_repo.update_message_status.return_value = object()
    workflow = LLMGenerationWorkerWorkflow(
        uow=uow,
        llm_service=NonStreamingLLM(LLMResultDTO(content="answer")),
        rag_service=rag_service,
        rag_planning_service=planner,
    )
    payload = GenerationPayload(
        session_id=uuid.uuid4(),
        query_text="hi",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    await workflow.generate_nonstream(
        payload=payload, assistant_message_id=uuid.uuid4()
    )

    rag_service.retrieve.assert_awaited_once_with(
        query_text="hi",
        kb_id=payload.kb_id,
        top_k=4,
    )
