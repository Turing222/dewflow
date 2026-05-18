"""Worker-side LLM generation workflow.

职责：在 TaskIQ worker 中调用 LLM、发布流式 chunk / 返回完整结果，并拥有最终消息状态落库。
边界：Web 负责创建会话和消息占位；本 workflow 不做认证/鉴权/HTTP 响应。
失败处理：业务和系统异常都会尽力回写助手消息失败状态，并通过 Redis 通知等待方。
"""

import logging
import time
import uuid
from dataclasses import dataclass

import redis.asyncio as redis

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.ai.core.token_counter import count_tokens
from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
)
from backend.application.chat.worker_persistence_handler import WorkerPersistenceHandler
from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.contracts.interfaces import (
    AbstractLLMService,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.core.concurrency import llm_concurrency_slot
from backend.core.exceptions import AppException
from backend.infra.redis import RedisClient
from backend.models.schemas.chat.dto import LLMQueryDTO
from backend.models.schemas.chat.payloads import GenerationPayload, GenerationResult
from backend.observability.trace_utils import (
    build_llm_span_attributes,
    set_span_attributes,
    trace_span,
)
from backend.services.chat_safety_metadata import (
    SAFETY_REFUSAL_MESSAGE,
    BadcaseReason,
    BadcaseSeverity,
    GuardrailDecision,
    ResponseOutcome,
    build_safety_metadata,
    evaluate_input_guardrail,
    evaluate_output_guardrail,
)
from backend.services.rag_evidence_policy import RAGEvidencePolicy
from backend.services.rag_planning_service import RAGPlanningService

logger = logging.getLogger(__name__)


@dataclass
class _RAGRefusalSignal(Exception):
    """Signal from _prepare_generation when RAG refuses to answer."""

    search_context: dict | None


class LLMGenerationWorkerWorkflow:
    """Worker-side LLM generation and persistence workflow."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        redis_client: RedisClient,
        llm_service: AbstractLLMService,
        rag_service: AbstractRAGService | None = None,
        rag_planning_service: RAGPlanningService | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
        rag_evidence_policy: RAGEvidencePolicy | None = None,
    ) -> None:
        self._redis_client = redis_client
        self.uow = uow
        self.llm_service = llm_service
        self.rag_orchestrator = WorkerRAGOrchestrator(
            rag_service=rag_service,
            rag_planning_service=rag_planning_service,
            chat_context_builder=chat_context_builder,
            rag_evidence_policy=rag_evidence_policy,
        )
        self.persistence_handler = WorkerPersistenceHandler(
            uow=uow,
            redis_client=redis_client,
        )

    async def _redis(self) -> redis.Redis:
        return await self._redis_client.init()

    async def _publish(self, channel: str, payload: str) -> None:
        redis_connection = await self._redis()
        await redis_connection.publish(channel, payload)

    async def _set_idempotency_message(
        self,
        *,
        idempotency_lock_key: str | None,
        assistant_message_id: uuid.UUID | None,
    ) -> None:
        if idempotency_lock_key is None or assistant_message_id is None:
            return
        redis_connection = await self._redis()
        await redis_connection.set(
            idempotency_lock_key,
            str(assistant_message_id),
            ex=3600,
        )

    # ── Shared Internal Helpers ───────────────────────────────────

    async def _prepare_generation(
        self,
        payload: GenerationPayload,
    ) -> tuple[LLMQueryDTO, int, dict | None]:
        """RAG context -> LLMQueryDTO + tokens_input + search_context.

        Raises _RAGRefusalSignal when RAG refuses to answer.
        Raises RuntimeError when assembled prompt is missing.
        """
        prepared_context = await self.rag_orchestrator.prepare_context(payload)
        if prepared_context.refusal_decision is not None:
            raise _RAGRefusalSignal(search_context=prepared_context.search_context)
        assembled = prepared_context.assembled_prompt
        if assembled is None:
            raise RuntimeError("生成上下文缺少 Prompt")
        search_context = prepared_context.search_context
        tokens_input = assembled.total_tokens
        llm_query = LLMQueryDTO(
            session_id=payload.session_id,
            query_text=payload.query_text,
            conversation_history=assembled.messages,
            extra_body=payload.extra_body,
        )
        return llm_query, tokens_input, search_context

    async def _on_success(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict[str, object],
        idempotency_lock_key: str | None,
    ) -> None:
        """Orchestrate persist_success + idempotency lock write."""
        await self.persistence_handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=content,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=message_metadata,
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await self._set_idempotency_message(
                idempotency_lock_key=idempotency_lock_key,
                assistant_message_id=assistant_message_id,
            )

    async def _persist_refusal(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict[str, object],
        idempotency_lock_key: str | None,
    ) -> None:
        """Shared refusal/block persistence + idempotency lock write."""
        await self.persistence_handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=content,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=message_metadata,
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await self._set_idempotency_message(
                idempotency_lock_key=idempotency_lock_key,
                assistant_message_id=assistant_message_id,
            )

    async def _handle_generation_error(
        self,
        exc: Exception,
        *,
        assistant_message_id: uuid.UUID | None,
        idempotency_lock_key: str | None,
        channel: str | None = None,
    ) -> GenerationResult:
        """Common error handling: persist failure, optionally publish, return result."""
        if isinstance(exc, AppException):
            logger.warning("TaskIQ 调用 LLM 业务异常: %s", exc)
            error_content = str(exc)
        else:
            logger.exception("TaskIQ 调用 LLM 系统异常")
            error_content = "服务暂时不可用，请稍后重试"

        await self.persistence_handler.persist_failure(
            assistant_message_id=assistant_message_id,
            error_content=error_content,
            idempotency_lock_key=idempotency_lock_key,
        )

        if channel is not None:
            await self._publish(channel, encode_error_event(error_content))

        return GenerationResult(success=False, error=error_content)

    def _build_span_attributes(
        self,
        *,
        stream: bool,
        session_id: uuid.UUID,
        assistant_message_id: uuid.UUID | None,
        tokens_input: int,
        search_context: dict | None,
        channel: str | None = None,
    ) -> dict[str, object]:
        """Build OTel span attributes shared by stream and non-stream paths."""
        attrs: dict[str, object] = {
            **build_llm_span_attributes(
                provider=getattr(self.llm_service, "provider_name", "unknown"),
                model=getattr(self.llm_service, "model_name", "unknown"),
                operation="generate",
                stream=stream,
            ),
            "chat.session_id": session_id,
            "chat.assistant_message_id": assistant_message_id,
            "chat.prompt.tokens_input": tokens_input,
            "chat.prompt.uses_rag": search_context is not None,
            "llm.provider": getattr(self.llm_service, "provider_name", "unknown"),
        }
        if channel is not None:
            attrs["redis.channel"] = channel
        return attrs

    # ── Streaming ──────────────────────────────────────────────────

    async def generate_stream(
        self,
        *,
        payload: GenerationPayload,
        channel: str,
        assistant_message_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        idempotency_lock_key: str | None = None,
    ) -> str | None:
        """Generate a streaming answer, publish chunks, and persist final state.

        Returns an error string on failure, or None on success / guardrail block.
        """
        accumulated_content: list[str] = []
        done_published: bool = False
        output_decision: GuardrailDecision | None = None
        output_blocked = False
        start_time = time.time()

        try:
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                await self._handle_stream_input_block(
                    channel=channel,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return
            try:
                llm_query, tokens_input, search_context = (
                    await self._prepare_generation(payload)
                )
            except _RAGRefusalSignal as sig:
                await self._handle_stream_refusal(
                    channel=channel,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    search_context=sig.search_context,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return

            with trace_span(
                "taskiq.llm_stream.generate_and_publish",
                self._build_span_attributes(
                    stream=True,
                    session_id=payload.session_id,
                    assistant_message_id=assistant_message_id,
                    tokens_input=tokens_input,
                    search_context=search_context,
                    channel=channel,
                ),
            ) as span:
                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "chat.assistant_message_id": assistant_message_id,
                        "chat.stream": True,
                    }
                ):
                    async for chunk in self.llm_service.stream_response(llm_query):
                        candidate_content = "".join([*accumulated_content, chunk])
                        output_decision = evaluate_output_guardrail(candidate_content)
                        if output_decision.triggered:
                            # Provider streaming lacks a cancel token here, so we stop
                            # consuming before unsafe content is published and rely on
                            # future provider-level cancellation to reduce token waste.
                            accumulated_content.append(chunk)
                            output_blocked = True
                            await self._publish(
                                channel,
                                encode_chunk_event(SAFETY_REFUSAL_MESSAGE),
                            )
                            break
                        accumulated_content.append(chunk)
                        await self._publish(
                            channel,
                            encode_chunk_event(chunk),
                        )

                full_content = "".join(accumulated_content)
                if output_blocked:
                    if output_decision is None:
                        output_decision = evaluate_output_guardrail(full_content)
                    content_to_persist = SAFETY_REFUSAL_MESSAGE
                else:
                    output_decision = evaluate_output_guardrail(full_content)
                    content_to_persist = full_content
                tokens_output = self._count_output_tokens(content_to_persist)
                await self._on_success(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    content=content_to_persist,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    search_context=search_context,
                    start_time=start_time,
                    message_metadata=self._build_success_metadata(
                        output_decision=output_decision,
                        original_content=full_content,
                    ),
                    idempotency_lock_key=idempotency_lock_key,
                )

                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": len(accumulated_content),
                        "llm.response.char_count": len(full_content),
                        "chat.tokens_input": tokens_input,
                        "chat.tokens_output": tokens_output,
                        "gen_ai.usage.input_tokens": tokens_input,
                        "gen_ai.usage.output_tokens": tokens_output,
                    },
                )
            logger.info("TaskIQ Worker 成功结束流式处理: %s", channel)
        except (AppException, Exception) as exc:
            result = await self._handle_generation_error(
                exc,
                assistant_message_id=assistant_message_id,
                idempotency_lock_key=idempotency_lock_key,
                channel=channel,
            )
            return result.error
        finally:
            if not done_published:
                await self._publish(channel, encode_done_event())

    # ── Non-Streaming ──────────────────────────────────────────────

    async def generate_nonstream(
        self,
        *,
        payload: GenerationPayload,
        assistant_message_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        idempotency_lock_key: str | None = None,
    ) -> GenerationResult:
        """Generate a non-streaming answer, persist final state, and return result."""
        start_time = time.time()

        try:
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                return await self._handle_nonstream_input_block(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
            try:
                llm_query, tokens_input, search_context = (
                    await self._prepare_generation(payload)
                )
            except _RAGRefusalSignal as sig:
                return await self._handle_nonstream_refusal(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    search_context=sig.search_context,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )

            with trace_span(
                "taskiq.llm_nonstream.generate",
                self._build_span_attributes(
                    stream=False,
                    session_id=payload.session_id,
                    assistant_message_id=assistant_message_id,
                    tokens_input=tokens_input,
                    search_context=search_context,
                ),
            ) as span:
                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "chat.assistant_message_id": assistant_message_id,
                        "chat.stream": False,
                    }
                ):
                    result = await self.llm_service.generate_response(llm_query)
                set_span_attributes(
                    span,
                    {
                        "llm.success": result.success,
                        "llm.latency_ms": result.latency_ms,
                        "llm.response.completion_tokens": result.completion_tokens,
                        "llm.response.char_count": len(result.content),
                        "gen_ai.usage.input_tokens": result.prompt_tokens,
                        "gen_ai.usage.output_tokens": result.completion_tokens,
                    },
                )

            if not result.success:
                error_msg = result.error_message or "LLM 服务返回失败"
                await self.persistence_handler.persist_failure(
                    assistant_message_id=assistant_message_id,
                    error_content=error_msg,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return GenerationResult(success=False, error=error_msg)

            original_content = result.content
            output_decision = evaluate_output_guardrail(original_content)
            full_content = (
                SAFETY_REFUSAL_MESSAGE
                if output_decision.triggered
                else original_content
            )
            tokens_output = (
                self._count_output_tokens(full_content)
                if output_decision.triggered
                else result.completion_tokens or self._count_output_tokens(full_content)
            )

            await self._on_success(
                assistant_message_id=assistant_message_id,
                user_id=user_id,
                content=full_content,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                search_context=search_context,
                start_time=start_time,
                message_metadata=self._build_success_metadata(
                    output_decision=output_decision,
                    original_content=original_content,
                ),
                idempotency_lock_key=idempotency_lock_key,
            )

            logger.info(
                "TaskIQ Worker 成功结束非流式处理: session_id=%s, message_id=%s",
                payload.session_id,
                assistant_message_id,
            )
            return GenerationResult(
                success=True,
                content=full_content,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                search_context=search_context,
                latency_ms=result.latency_ms,
            )

        except (AppException, Exception) as exc:
            return await self._handle_generation_error(
                exc,
                assistant_message_id=assistant_message_id,
                idempotency_lock_key=idempotency_lock_key,
            )

    # ── Shared Helpers ─────────────────────────────────────────────

    async def _handle_stream_input_block(
        self,
        *,
        channel: str,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        input_decision: GuardrailDecision,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> None:
        tokens_output = self._count_output_tokens(SAFETY_REFUSAL_MESSAGE)
        await self._publish(
            channel,
            encode_chunk_event(SAFETY_REFUSAL_MESSAGE),
        )
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=SAFETY_REFUSAL_MESSAGE,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=None,
            start_time=start_time,
            message_metadata=build_safety_metadata(
                response_outcome=ResponseOutcome.BLOCKED,
                input_decision=input_decision,
            ),
            idempotency_lock_key=idempotency_lock_key,
        )

    async def _handle_stream_refusal(
        self,
        *,
        channel: str,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search_context: dict | None,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> None:
        refusal_content = ai_settings.RAG_REFUSAL_MESSAGE
        tokens_output = self._count_output_tokens(refusal_content)
        await self._publish(channel, encode_chunk_event(refusal_content))
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=self._build_rag_refusal_metadata(),
            idempotency_lock_key=idempotency_lock_key,
        )

    async def _handle_nonstream_input_block(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        input_decision: GuardrailDecision,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> GenerationResult:
        tokens_output = self._count_output_tokens(SAFETY_REFUSAL_MESSAGE)
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=SAFETY_REFUSAL_MESSAGE,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=None,
            start_time=start_time,
            message_metadata=build_safety_metadata(
                response_outcome=ResponseOutcome.BLOCKED,
                input_decision=input_decision,
            ),
            idempotency_lock_key=idempotency_lock_key,
        )
        return GenerationResult(
            success=True,
            content=SAFETY_REFUSAL_MESSAGE,
            tokens_input=0,
            tokens_output=tokens_output,
        )

    async def _handle_nonstream_refusal(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search_context: dict | None,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> GenerationResult:
        refusal_content = ai_settings.RAG_REFUSAL_MESSAGE
        tokens_output = self._count_output_tokens(refusal_content)
        await self._persist_refusal(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=self._build_rag_refusal_metadata(),
            idempotency_lock_key=idempotency_lock_key,
        )
        return GenerationResult(
            success=True,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
        )

    def _count_output_tokens(self, content: str) -> int:
        model_name = getattr(
            self.llm_service,
            "model_name",
            get_llm_model_config().resolve_profile().model,
        )
        return count_tokens(content, model_name)

    @staticmethod
    def _build_rag_refusal_metadata() -> dict[str, object]:
        return build_safety_metadata(
            response_outcome=ResponseOutcome.REFUSED,
            badcase_severity=BadcaseSeverity.P1,
            badcase_reason=BadcaseReason.EMPTY_RETRIEVAL_REFUSAL,
        )

    @staticmethod
    def _build_success_metadata(
        *,
        output_decision: GuardrailDecision,
        original_content: str,
    ) -> dict[str, object]:
        if not output_decision.triggered:
            return build_safety_metadata(response_outcome=ResponseOutcome.ANSWERED)
        return build_safety_metadata(
            response_outcome=ResponseOutcome.REFUSED,
            output_decision=output_decision,
            original_unsafe_output=original_content,
            badcase_severity=BadcaseSeverity.P0,
            badcase_reason=BadcaseReason.SHOULD_REFUSE_BUT_ANSWERED,
        )
