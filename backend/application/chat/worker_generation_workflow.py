"""Worker-side LLM generation workflow.

职责：在 TaskIQ worker 中调用 LLM、发布流式 chunk / 返回完整结果，并拥有最终消息状态落库。
边界：Web 负责创建会话和消息占位；本 workflow 不做认证/鉴权/HTTP 响应。
失败处理：业务和系统异常都会尽力回写助手消息失败状态，并通过 Redis 通知等待方。
"""

import logging
import time
import uuid
from dataclasses import dataclass

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.application.chat.timing import (
    elapsed_ms,
    merge_metrics,
    perf_start,
    tokens_per_second,
)
from backend.application.chat.worker_guardrail_handler import WorkerGuardrailHandler
from backend.application.chat.worker_persistence_handler import WorkerPersistenceHandler
from backend.application.chat.worker_rag_orchestrator import WorkerRAGOrchestrator
from backend.application.chat.worker_stream_publisher import WorkerStreamPublisher
from backend.config.llm import get_llm_model_config
from backend.contracts.interfaces import (
    AbstractExternalContextProvider,
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
    GuardrailDecision,
    build_guardrail_success_metadata,
    evaluate_input_guardrail,
    evaluate_output_guardrail,
)
from backend.services.citation_validator import (
    CitationResult,
    StreamingCitationFilter,
    extract_valid_ref_ids,
    validate_citations,
)
from backend.services.rag_evidence_policy import RAGEvidencePolicy
from backend.services.rag_planning_service import RAGPlanningService
from backend.utils.token_estimation import count_tokens

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
        external_context_provider: AbstractExternalContextProvider | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
        rag_evidence_policy: RAGEvidencePolicy | None = None,
        rag_orchestrator: WorkerRAGOrchestrator | None = None,
        persistence_handler: WorkerPersistenceHandler | None = None,
        stream_publisher: WorkerStreamPublisher | None = None,
        guardrail_handler: WorkerGuardrailHandler | None = None,
    ) -> None:
        self._redis_client = redis_client
        self.uow = uow
        self.llm_service = llm_service
        self.rag_orchestrator = rag_orchestrator or WorkerRAGOrchestrator(
            rag_service=rag_service,
            rag_planning_service=rag_planning_service,
            external_context_provider=external_context_provider,
            chat_context_builder=chat_context_builder,
            rag_evidence_policy=rag_evidence_policy,
        )
        self.persistence_handler = persistence_handler or WorkerPersistenceHandler(
            uow=uow,
            redis_client=redis_client,
        )
        self.stream_publisher = stream_publisher or WorkerStreamPublisher(
            redis_client=redis_client,
        )
        self.guardrail_handler = guardrail_handler or WorkerGuardrailHandler(
            persistence_handler=self.persistence_handler,
            stream_publisher=self.stream_publisher,
            count_output_tokens=self._count_output_tokens,
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
            await self.stream_publisher.publish_error(channel, error_content)

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

    async def _persist_success_and_idempotency(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict | None,
        idempotency_lock_key: str | None,
        model_name: str = "default",
    ) -> None:
        """Persist success state and write idempotency marker if applicable."""
        await self.persistence_handler.persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=content,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=message_metadata,
            model_name=model_name,
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await self.persistence_handler.write_idempotency_message(
                idempotency_lock_key=idempotency_lock_key,
                assistant_message_id=assistant_message_id,
            )

    def _count_output_tokens(self, content: str) -> int:
        model_name = getattr(
            self.llm_service,
            "model_name",
            get_llm_model_config().resolve_profile().model,
        )
        return count_tokens(content, model_name)

    @staticmethod
    def _enrich_metadata_with_citation(
        metadata: dict[str, object],
        *,
        citation_result: CitationResult | None,
    ) -> dict[str, object]:
        if citation_result is not None:
            metadata["citation"] = {
                "total": citation_result.total_citations,
                "removed_count": citation_result.removed_count,
            }
        return metadata

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
        worker_started = perf_start()

        try:
            await self.stream_publisher.publish_started(channel)
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                await self.guardrail_handler.handle_stream_input_block(
                    channel=channel,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return
            try:
                (
                    llm_query,
                    tokens_input,
                    search_context,
                ) = await self._prepare_generation(payload)
            except _RAGRefusalSignal as sig:
                await self.guardrail_handler.handle_stream_refusal(
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
                citation_filter: StreamingCitationFilter | None = None
                if search_context is not None:
                    valid_ref_ids = extract_valid_ref_ids(search_context)
                    if valid_ref_ids:
                        citation_filter = StreamingCitationFilter(valid_ref_ids)
                llm_started = perf_start()
                # Worker first token: worker generation start -> first user-visible
                # chunk publish. Web records e2e_first_token_ms from HTTP entry.
                first_token_latency_ms: int | None = None
                first_published_from_llm_ms: int | None = None

                async def publish_user_chunk(content: str) -> None:
                    nonlocal first_token_latency_ms
                    nonlocal first_published_from_llm_ms
                    if first_token_latency_ms is None:
                        first_token_latency_ms = elapsed_ms(worker_started)
                        first_published_from_llm_ms = elapsed_ms(llm_started)
                    await self.stream_publisher.publish_chunk(channel, content)

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
                            accumulated_content.append(chunk)
                            output_blocked = True
                            await publish_user_chunk(SAFETY_REFUSAL_MESSAGE)
                            break
                        accumulated_content.append(chunk)
                        if citation_filter is not None:
                            cleaned = citation_filter.push(chunk)
                            if cleaned is not None:
                                await publish_user_chunk(cleaned)
                        else:
                            await publish_user_chunk(chunk)
                    if not output_blocked and citation_filter is not None:
                        remaining = citation_filter.flush()
                        if remaining:
                            await publish_user_chunk(remaining)
                llm_generate_ms = elapsed_ms(llm_started)

                full_content = "".join(accumulated_content)
                if output_blocked:
                    if output_decision is None:
                        output_decision = evaluate_output_guardrail(full_content)
                    content_to_persist = SAFETY_REFUSAL_MESSAGE
                else:
                    output_decision = evaluate_output_guardrail(full_content)
                    content_to_persist = full_content
                citation_result: CitationResult | None = None
                if (
                    not output_blocked
                    and search_context is not None
                    and content_to_persist
                ):
                    valid_ref_ids = extract_valid_ref_ids(search_context)
                    if valid_ref_ids:
                        citation_validate_started = perf_start()
                        citation_result = validate_citations(
                            content_to_persist, valid_ref_ids
                        )
                        search_context = merge_metrics(
                            search_context,
                            {
                                "citation_validate_ms": elapsed_ms(
                                    citation_validate_started
                                )
                            },
                        )
                        content_to_persist = citation_result.cleaned_content
                tokens_output = self._count_output_tokens(content_to_persist)
                worker_total_latency_ms = elapsed_ms(worker_started)
                await self._persist_success_and_idempotency(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    content=content_to_persist,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    search_context=search_context,
                    start_time=start_time,
                    message_metadata=merge_metrics(
                        self._enrich_metadata_with_citation(
                            build_guardrail_success_metadata(
                                output_decision=output_decision,
                                original_content=full_content,
                            ),
                            citation_result=citation_result,
                        ),
                        {
                            "worker_total_latency_ms": worker_total_latency_ms,
                            "llm_first_token_ms": first_published_from_llm_ms,
                            "first_token_latency_ms": first_token_latency_ms,
                            "llm_generate_ms": llm_generate_ms,
                            "tokens_input": tokens_input,
                            "tokens_output": tokens_output,
                            "tokens_per_second": tokens_per_second(
                                tokens_output,
                                llm_generate_ms,
                            ),
                        },
                    ),
                    idempotency_lock_key=idempotency_lock_key,
                    model_name=payload.billing_model_name,
                )

                citation_attrs: dict[str, object] = {}
                if citation_result is not None:
                    citation_attrs = {
                        "citation.total": citation_result.total_citations,
                        "citation.valid": citation_result.total_citations
                        - citation_result.removed_count,
                        "citation.removed": citation_result.removed_count,
                    }
                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": len(accumulated_content),
                        "llm.response.char_count": len(full_content),
                        "llm.first_token_ms": first_published_from_llm_ms,
                        "chat.first_token_latency_ms": first_token_latency_ms,
                        "chat.worker_total_latency_ms": worker_total_latency_ms,
                        "chat.tokens_input": tokens_input,
                        "chat.tokens_output": tokens_output,
                        "gen_ai.usage.input_tokens": tokens_input,
                        "gen_ai.usage.output_tokens": tokens_output,
                        **citation_attrs,
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
                await self.stream_publisher.publish_done(channel)

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
        worker_started = perf_start()

        try:
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                return await self.guardrail_handler.handle_nonstream_input_block(
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
            try:
                (
                    llm_query,
                    tokens_input,
                    search_context,
                ) = await self._prepare_generation(payload)
            except _RAGRefusalSignal as sig:
                return await self.guardrail_handler.handle_nonstream_refusal(
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
                    llm_started = perf_start()
                    result = await self.llm_service.generate_response(llm_query)
                    llm_generate_ms = elapsed_ms(llm_started)
                set_span_attributes(
                    span,
                    {
                        "llm.success": result.success,
                        "llm.latency_ms": result.latency_ms,
                        "llm.generate_ms": llm_generate_ms,
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
            citation_result: CitationResult | None = None
            if (
                not output_decision.triggered
                and search_context is not None
                and full_content
            ):
                valid_ref_ids = extract_valid_ref_ids(search_context)
                if valid_ref_ids:
                    citation_validate_started = perf_start()
                    citation_result = validate_citations(full_content, valid_ref_ids)
                    search_context = merge_metrics(
                        search_context,
                        {"citation_validate_ms": elapsed_ms(citation_validate_started)},
                    )
                    full_content = citation_result.cleaned_content
            tokens_output = (
                self._count_output_tokens(full_content)
                if output_decision.triggered
                else result.completion_tokens or self._count_output_tokens(full_content)
            )
            worker_total_latency_ms = elapsed_ms(worker_started)

            await self._persist_success_and_idempotency(
                assistant_message_id=assistant_message_id,
                user_id=user_id,
                content=full_content,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                search_context=search_context,
                start_time=start_time,
                message_metadata=merge_metrics(
                    self._enrich_metadata_with_citation(
                        build_guardrail_success_metadata(
                            output_decision=output_decision,
                            original_content=original_content,
                        ),
                        citation_result=citation_result,
                    ),
                    {
                        "worker_total_latency_ms": worker_total_latency_ms,
                        "llm_generate_ms": llm_generate_ms,
                        "tokens_input": tokens_input,
                        "tokens_output": tokens_output,
                        "tokens_per_second": tokens_per_second(
                            tokens_output,
                            llm_generate_ms,
                        ),
                    },
                ),
                idempotency_lock_key=idempotency_lock_key,
                model_name=payload.billing_model_name,
            )

            if citation_result is not None:
                with trace_span(
                    "taskiq.llm_nonstream.citation_validate",
                    {
                        "citation.total": citation_result.total_citations,
                        "citation.valid": citation_result.total_citations
                        - citation_result.removed_count,
                        "citation.removed": citation_result.removed_count,
                    },
                ):
                    pass

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
