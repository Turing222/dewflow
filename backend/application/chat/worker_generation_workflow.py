"""Worker-side LLM generation workflow.

职责：在 TaskIQ worker 中调用 LLM、发布流式 chunk / 返回完整结果，并拥有最终消息状态落库。
边界：Web 负责创建会话和消息占位；本 workflow 不做认证/鉴权/HTTP 响应。
失败处理：业务和系统异常都会尽力回写助手消息失败状态，并通过 Redis 通知等待方。
"""

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.ai.core.token_counter import count_tokens
from backend.application.chat.stream_events import (
    encode_chunk_event,
    encode_done_event,
    encode_error_event,
)
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.contracts.interfaces import (
    AbstractLLMService,
    AbstractRAGService,
    AbstractUnitOfWork,
)
from backend.core.concurrency import llm_concurrency_slot
from backend.core.exceptions import AppException
from backend.infra.redis import redis_client
from backend.models.schemas.chat.dto import LLMQueryDTO
from backend.models.schemas.chat.payloads import GenerationPayload, GenerationResult
from backend.observability.trace_utils import set_span_attributes, trace_span
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
from backend.services.chat_service import ChatMessageUpdater
from backend.services.rag_evidence_policy import RAGEvidenceDecision, RAGEvidencePolicy
from backend.services.rag_planning_service import (
    RAG_PLANNER_FALLBACK_REASON,
    RAGExecutionPlan,
    RAGPlanningService,
)
from backend.services.rag_service import RAGService

logger = logging.getLogger(__name__)


@dataclass
class PreparedGenerationContext:
    """Worker 生成前准备好的 Prompt 或拒答决策。"""

    assembled_prompt: Any | None
    search_context: dict | None
    refusal_decision: RAGEvidenceDecision | None = None


class LLMGenerationWorkerWorkflow:
    """Worker-side LLM generation and persistence workflow."""

    def __init__(
        self,
        *,
        uow: AbstractUnitOfWork,
        llm_service: AbstractLLMService,
        rag_service: AbstractRAGService | None = None,
        rag_planning_service: RAGPlanningService | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
        rag_evidence_policy: RAGEvidencePolicy | None = None,
    ) -> None:
        self.uow = uow
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.rag_planning_service = rag_planning_service
        self.chat_context_builder = chat_context_builder or ChatContextBuilder()
        self.rag_evidence_policy = rag_evidence_policy or RAGEvidencePolicy()

    # ── Streaming ──────────────────────────────────────────────────

    async def generate_stream(
        self,
        *,
        payload: GenerationPayload,
        channel: str,
        assistant_message_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        idempotency_lock_key: str | None = None,
    ) -> None:
        """Generate a streaming answer, publish chunks, and persist final state."""
        redis_connection = await redis_client.init()
        accumulated_content: list[str] = []
        start_time = time.time()

        try:
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                await self._handle_stream_input_block(
                    channel=channel,
                    redis_connection=redis_connection,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return
            prepared_context = await self._prepare_context(payload)
            if prepared_context.refusal_decision is not None:
                await self._handle_stream_refusal(
                    channel=channel,
                    redis_connection=redis_connection,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    search_context=prepared_context.search_context,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
                return
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

            with trace_span(
                "taskiq.llm_stream.generate_and_publish",
                {
                    "redis.channel": channel,
                    "chat.session_id": payload.session_id,
                    "chat.assistant_message_id": assistant_message_id,
                    "chat.prompt.tokens_input": tokens_input,
                    "chat.prompt.uses_rag": search_context is not None,
                    "llm.provider": getattr(
                        self.llm_service, "provider_name", "unknown"
                    ),
                    "gen_ai.request.model": getattr(
                        self.llm_service, "model_name", "unknown"
                    ),
                },
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
                            await redis_connection.publish(
                                channel,
                                encode_chunk_event(SAFETY_REFUSAL_MESSAGE),
                            )
                            break
                        accumulated_content.append(chunk)
                        await redis_connection.publish(
                            channel,
                            encode_chunk_event(chunk),
                        )

                full_content = "".join(accumulated_content)
                output_decision = evaluate_output_guardrail(full_content)
                content_to_persist = (
                    SAFETY_REFUSAL_MESSAGE
                    if output_decision.triggered
                    else full_content
                )
                tokens_output = self._count_output_tokens(content_to_persist)
                await self._persist_success(
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
                )
                if (
                    idempotency_lock_key is not None
                    and assistant_message_id is not None
                ):
                    await redis_connection.set(
                        idempotency_lock_key,
                        str(assistant_message_id),
                        ex=3600,
                    )

                set_span_attributes(
                    span,
                    {
                        "llm.response.chunk_count": len(accumulated_content),
                        "llm.response.char_count": len(full_content),
                        "chat.tokens_input": tokens_input,
                        "chat.tokens_output": tokens_output,
                    },
                )
            logger.info("TaskIQ Worker 成功结束流式处理: %s", channel)
        except AppException as exc:
            logger.warning("TaskIQ 调用 LLM 业务异常: %s", exc)
            await self._persist_failure(
                assistant_message_id=assistant_message_id,
                error_content=str(exc),
                idempotency_lock_key=idempotency_lock_key,
            )
            await redis_connection.publish(channel, encode_error_event(str(exc)))
        except Exception:
            logger.exception("TaskIQ 调用 LLM 系统异常")
            await self._persist_failure(
                assistant_message_id=assistant_message_id,
                error_content="服务暂时不可用，请稍后重试",
                idempotency_lock_key=idempotency_lock_key,
            )
            await redis_connection.publish(
                channel,
                encode_error_event("服务暂时不可用，请稍后重试"),
            )
        finally:
            await redis_connection.publish(channel, encode_done_event())

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
        redis_connection = await redis_client.init()
        start_time = time.time()

        try:
            input_decision = evaluate_input_guardrail(payload.query_text)
            if input_decision.triggered:
                return await self._handle_nonstream_input_block(
                    redis_connection=redis_connection,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    input_decision=input_decision,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
            prepared_context = await self._prepare_context(payload)
            if prepared_context.refusal_decision is not None:
                return await self._handle_nonstream_refusal(
                    redis_connection=redis_connection,
                    assistant_message_id=assistant_message_id,
                    user_id=user_id,
                    search_context=prepared_context.search_context,
                    start_time=start_time,
                    idempotency_lock_key=idempotency_lock_key,
                )
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

            with trace_span(
                "taskiq.llm_nonstream.generate",
                {
                    "chat.session_id": payload.session_id,
                    "chat.assistant_message_id": assistant_message_id,
                    "chat.prompt.tokens_input": tokens_input,
                    "chat.prompt.uses_rag": search_context is not None,
                    "llm.provider": getattr(
                        self.llm_service, "provider_name", "unknown"
                    ),
                    "gen_ai.request.model": getattr(
                        self.llm_service, "model_name", "unknown"
                    ),
                },
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
                    },
                )

            if not result.success:
                error_msg = result.error_message or "LLM 服务返回失败"
                await self._persist_failure(
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

            await self._persist_success(
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
            )
            if idempotency_lock_key is not None and assistant_message_id is not None:
                await redis_connection.set(
                    idempotency_lock_key,
                    str(assistant_message_id),
                    ex=3600,
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

        except AppException as exc:
            logger.warning("TaskIQ 调用 LLM 业务异常: %s", exc)
            await self._persist_failure(
                assistant_message_id=assistant_message_id,
                error_content=str(exc),
                idempotency_lock_key=idempotency_lock_key,
            )
            return GenerationResult(success=False, error=str(exc))
        except Exception:
            logger.exception("TaskIQ 调用 LLM 系统异常")
            await self._persist_failure(
                assistant_message_id=assistant_message_id,
                error_content="服务暂时不可用，请稍后重试",
                idempotency_lock_key=idempotency_lock_key,
            )
            return GenerationResult(success=False, error="服务暂时不可用，请稍后重试")

    # ── Shared Helpers ─────────────────────────────────────────────

    async def _prepare_context(self, payload: GenerationPayload):
        rag_plan, planner_used = await self._build_rag_plan(payload)
        candidates = await self._retrieve_rag_candidates(payload, rag_plan)
        reranked_chunks = await self._rerank_candidates_if_enabled(
            payload,
            candidates,
            rag_plan,
        )
        refusal_decision = self.rag_evidence_policy.evaluate(
            kb_id=payload.kb_id,
            rag_plan=rag_plan,
            chunks=reranked_chunks,
        )
        if refusal_decision.should_refuse:
            search_context = self._build_refusal_search_context(
                payload=payload,
                chunks=reranked_chunks,
                decision=refusal_decision,
            )
            return PreparedGenerationContext(
                assembled_prompt=None,
                search_context=search_context,
                refusal_decision=refusal_decision,
            )
        with trace_span(
            "taskiq.llm_stream.prepare_context",
            {
                "chat.session_id": payload.session_id,
                "rag.kb_id": payload.kb_id,
                "rag.candidate_count": len(candidates),
                "rag.rerank.enabled": rag_plan.use_rerank,
                "rag.rerank.config_enabled": ai_settings.RAG_RERANK_ENABLED,
                "rag.hit_count": len(reranked_chunks),
                "rag.planner.enabled": ai_settings.RAG_PLANNER_ENABLED,
                "rag.planner.used": planner_used,
                "rag.planner.should_use_rag": rag_plan.should_use_rag,
                "rag.planner.retrieval_mode": rag_plan.retrieval_mode,
                "rag.planner.use_rerank": rag_plan.use_rerank,
                "rag.planner.fallback": (
                    rag_plan.reason == RAG_PLANNER_FALLBACK_REASON
                ),
            },
        ) as span:
            prepared_context = self.chat_context_builder.build_from_chunks(
                history_messages=payload.conversation_history,
                current_query=payload.query_text,
                kb_id=payload.kb_id,
                rag_chunks=reranked_chunks,
            )
            set_span_attributes(
                span,
                {
                    "chat.prompt.tokens_input": prepared_context.assembled_prompt.total_tokens,
                    "chat.prompt.message_count": len(
                        prepared_context.assembled_prompt.messages
                    ),
                    "chat.prompt.uses_rag": prepared_context.search_context is not None,
                },
            )
            return PreparedGenerationContext(
                assembled_prompt=prepared_context.assembled_prompt,
                search_context=prepared_context.search_context,
            )

    async def _handle_stream_input_block(
        self,
        *,
        channel: str,
        redis_connection: Any,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        input_decision: GuardrailDecision,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> None:
        tokens_output = self._count_output_tokens(SAFETY_REFUSAL_MESSAGE)
        await redis_connection.publish(
            channel,
            encode_chunk_event(SAFETY_REFUSAL_MESSAGE),
        )
        await self._persist_success(
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
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await redis_connection.set(
                idempotency_lock_key,
                str(assistant_message_id),
                ex=3600,
            )

    async def _handle_stream_refusal(
        self,
        *,
        channel: str,
        redis_connection: Any,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search_context: dict | None,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> None:
        refusal_content = ai_settings.RAG_REFUSAL_MESSAGE
        tokens_output = self._count_output_tokens(refusal_content)
        await redis_connection.publish(channel, encode_chunk_event(refusal_content))
        await self._persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=self._build_rag_refusal_metadata(),
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await redis_connection.set(
                idempotency_lock_key,
                str(assistant_message_id),
                ex=3600,
            )

    async def _handle_nonstream_input_block(
        self,
        *,
        redis_connection: Any,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        input_decision: GuardrailDecision,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> GenerationResult:
        tokens_output = self._count_output_tokens(SAFETY_REFUSAL_MESSAGE)
        await self._persist_success(
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
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await redis_connection.set(
                idempotency_lock_key,
                str(assistant_message_id),
                ex=3600,
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
        redis_connection: Any,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search_context: dict | None,
        start_time: float,
        idempotency_lock_key: str | None,
    ) -> GenerationResult:
        refusal_content = ai_settings.RAG_REFUSAL_MESSAGE
        tokens_output = self._count_output_tokens(refusal_content)
        await self._persist_success(
            assistant_message_id=assistant_message_id,
            user_id=user_id,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
            start_time=start_time,
            message_metadata=self._build_rag_refusal_metadata(),
        )
        if idempotency_lock_key is not None and assistant_message_id is not None:
            await redis_connection.set(
                idempotency_lock_key,
                str(assistant_message_id),
                ex=3600,
            )
        return GenerationResult(
            success=True,
            content=refusal_content,
            tokens_input=0,
            tokens_output=tokens_output,
            search_context=search_context,
        )

    async def _build_rag_plan(
        self,
        payload: GenerationPayload,
    ) -> tuple[RAGExecutionPlan, bool]:
        default_plan = RAGExecutionPlan.from_settings(
            has_kb=payload.kb_id is not None,
            query_text=payload.query_text,
        )
        if payload.rag_candidates:
            return default_plan, False
        if payload.kb_id is None or not payload.query_text.strip():
            return default_plan, False
        if not ai_settings.RAG_PLANNER_ENABLED:
            return default_plan, False
        if self.rag_planning_service is None:
            return default_plan, False

        try:
            plan = await self.rag_planning_service.plan(
                query_text=payload.query_text,
                conversation_history=payload.conversation_history,
                kb_id=payload.kb_id,
            )
            return plan.clamped(), True
        except Exception as exc:
            logger.warning("Worker RAG Planner 规划失败，降级为默认计划: %s", exc)
            return default_plan, False

    async def _retrieve_rag_candidates(
        self,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        if payload.rag_candidates:
            return list(payload.rag_candidates)
        if (
            self.rag_service is None
            or payload.kb_id is None
            or not rag_plan.should_use_rag
        ):
            return []

        try:
            uow = getattr(self.rag_service, "uow", None)
            if uow is None or getattr(uow, "_session", None) is not None:
                return await self._retrieve_from_rag_service(payload, rag_plan)
            async with uow:
                return await self._retrieve_from_rag_service(payload, rag_plan)
        except Exception as exc:
            logger.warning("Worker RAG 候选检索失败，降级为普通对话: %s", exc)
            return []

    async def _retrieve_from_rag_service(
        self,
        payload: GenerationPayload,
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        if self.rag_service is None:
            return []
        if rag_plan.retrieval_mode == "fulltext":
            fulltext_top_k = (
                rag_plan.candidate_count if rag_plan.use_rerank else rag_plan.top_k
            )
            return await self.rag_service.retrieve_fulltext(
                query_text=payload.query_text,
                kb_id=payload.kb_id,
                top_k=fulltext_top_k,
            )
        if rag_plan.retrieval_mode == "hybrid" or rag_plan.use_rerank:
            hybrid_top_k = (
                rag_plan.candidate_count if rag_plan.use_rerank else rag_plan.top_k
            )
            return await self.rag_service.retrieve_hybrid(
                query_text=payload.query_text,
                kb_id=payload.kb_id,
                top_k=hybrid_top_k,
            )
        return await self.rag_service.retrieve(
            query_text=payload.query_text,
            kb_id=payload.kb_id,
            top_k=rag_plan.top_k,
        )

    async def _rerank_candidates_if_enabled(
        self,
        payload: GenerationPayload,
        candidates: list[dict[str, Any]],
        rag_plan: RAGExecutionPlan,
    ) -> list[dict[str, Any]]:
        candidates = list(candidates)
        if not candidates:
            return []

        if not rag_plan.use_rerank:
            return candidates[: rag_plan.top_k]

        limit = max(1, rag_plan.rerank_top_k)
        try:
            with trace_span(
                "taskiq.llm_stream.rerank",
                {
                    "chat.session_id": payload.session_id,
                    "rag.kb_id": payload.kb_id,
                    "rag.top_k": limit,
                    "rag.candidate_count": len(candidates),
                    "rag.planner.use_rerank": rag_plan.use_rerank,
                },
            ) as span:
                prompt = RAGService._build_rerank_prompt(
                    query_text=payload.query_text,
                    candidates=candidates,
                )
                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "rag.kb_id": payload.kb_id,
                        "rag.rerank": True,
                    }
                ):
                    result = await self.llm_service.generate_response(
                        LLMQueryDTO(
                            session_id=payload.session_id,
                            query_text=prompt,
                            conversation_history=[],
                        )
                    )
                if not result.success:
                    raise ValueError(result.error_message or "LLM rerank failed")
                rankings = RAGService._parse_rerank_response(result.content)
                reranked = RAGService._apply_rankings(
                    candidates=candidates,
                    rankings=rankings,
                    limit=limit,
                )
                set_span_attributes(
                    span,
                    {
                        "rag.rerank.ranking_count": len(rankings),
                        "rag.hit_count": len(reranked),
                    },
                )
                return reranked
        except Exception as exc:
            logger.warning("Worker RAG rerank 失败，降级为候选原始排序: %s", exc)
            return candidates[:limit]

    def _build_refusal_search_context(
        self,
        *,
        payload: GenerationPayload,
        chunks: list[dict[str, Any]],
        decision: RAGEvidenceDecision,
    ) -> dict:
        search_context = self.chat_context_builder.build_search_context(
            kb_id=payload.kb_id,
            query_text=payload.query_text,
            rag_chunks=chunks,
        ) or {
            "version": 1,
            "kb_id": str(payload.kb_id) if payload.kb_id else None,
            "query": payload.query_text,
            "retrieval": {
                "hit_count": len(chunks),
                "source_count": 0,
                "max_score": decision.best_score or 0.0,
                "avg_score": decision.best_score or 0.0,
            },
            "refs": [],
            "chunks": [],
        }
        search_context.update(decision.to_metadata())
        return search_context

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

    async def _persist_success(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        content: str,
        tokens_input: int | None,
        tokens_output: int,
        search_context: dict | None,
        start_time: float,
        message_metadata: dict | None = None,
    ) -> None:
        if assistant_message_id is None:
            return

        async with self.uow:
            updater = ChatMessageUpdater(self.uow)
            await updater.update_as_success(
                message_id=assistant_message_id,
                content=content,
                start_time=start_time,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                search_context=search_context,
                message_metadata=message_metadata,
            )
            if user_id is None or tokens_input is None:
                return

            total_tokens = tokens_input + tokens_output
            ok = await self.uow.user_repo.increment_used_tokens_guarded(
                user_id,
                total_tokens,
            )
            if not ok:
                logger.warning(
                    "Token 累加后超出上限，本次消耗未记录: user_id=%s, delta=%d",
                    user_id,
                    total_tokens,
                )

    async def _persist_failure(
        self,
        *,
        assistant_message_id: uuid.UUID | None,
        error_content: str,
        idempotency_lock_key: str | None,
    ) -> None:
        if idempotency_lock_key is not None:
            try:
                redis_connection = await redis_client.init()
                await redis_connection.delete(idempotency_lock_key)
            except Exception:
                logger.debug(
                    "Worker 清理幂等锁失败: key=%s",
                    idempotency_lock_key,
                    exc_info=True,
                )

        if assistant_message_id is None:
            return

        try:
            async with self.uow:
                updater = ChatMessageUpdater(self.uow)
                await updater.update_as_failed(
                    message_id=assistant_message_id,
                    error_content=error_content,
                    message_metadata=build_safety_metadata(
                        response_outcome=ResponseOutcome.FAILED,
                    ),
                )
        except Exception:
            logger.exception(
                "Worker 回写助手消息失败状态异常: message_id=%s",
                assistant_message_id,
            )
