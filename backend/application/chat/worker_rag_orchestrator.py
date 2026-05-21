"""Worker-side RAG context orchestration.

职责：为 worker 生成流程准备 RAG plan、检索候选、rerank 结果和证据拒答上下文。
边界：本模块不调用 LLM 生成答案，不持久化消息，也不发布 Redis 流式事件。
"""

import logging
from dataclasses import dataclass
from typing import Any

from backend.ai.core.chat_context_builder import ChatContextBuilder
from backend.application.chat.timing import elapsed_ms, merge_metrics, perf_start
from backend.config.ai_settings import ai_settings
from backend.contracts.interfaces import AbstractRAGService
from backend.core.concurrency import llm_concurrency_slot
from backend.models.schemas.chat.payloads import GenerationPayload
from backend.observability.trace_utils import set_span_attributes, trace_span
from backend.services.rag_evidence_policy import RAGEvidenceDecision, RAGEvidencePolicy
from backend.services.rag_planning_service import (
    RAG_PLANNER_FALLBACK_REASON,
    RAGExecutionPlan,
    RAGPlanningService,
)

logger = logging.getLogger(__name__)


@dataclass
class PreparedGenerationContext:
    """Worker 生成前准备好的 Prompt 或拒答决策。"""

    assembled_prompt: Any | None
    search_context: dict | None
    refusal_decision: RAGEvidenceDecision | None = None


class WorkerRAGOrchestrator:
    """Worker-side RAG retrieval, rerank, and context assembly."""

    def __init__(
        self,
        *,
        rag_service: AbstractRAGService | None = None,
        rag_planning_service: RAGPlanningService | None = None,
        chat_context_builder: ChatContextBuilder | None = None,
        rag_evidence_policy: RAGEvidencePolicy | None = None,
    ) -> None:
        self.rag_service = rag_service
        self.rag_planning_service = rag_planning_service
        self.chat_context_builder = chat_context_builder or ChatContextBuilder()
        self.rag_evidence_policy = rag_evidence_policy or RAGEvidencePolicy()

    async def prepare_context(
        self,
        payload: GenerationPayload,
    ) -> PreparedGenerationContext:
        with trace_span(
            "taskiq.llm_stream.prepare_context",
            {
                "chat.session_id": payload.session_id,
                "rag.kb_id": payload.kb_id,
            },
        ) as span:
            metrics: dict[str, object] = {}
            planner_started = perf_start()
            rag_plan, planner_used = await self.build_rag_plan(payload)
            metrics["planner_ms"] = elapsed_ms(planner_started)
            metrics["planner_used"] = planner_used
            metrics["retrieval_mode"] = rag_plan.retrieval_mode
            metrics["rerank_used"] = rag_plan.use_rerank

            retrieve_started = perf_start()
            candidates = await self.retrieve_rag_candidates(payload, rag_plan)
            metrics["retrieve_ms"] = elapsed_ms(retrieve_started)
            metrics["candidate_count"] = len(candidates)

            rerank_started = perf_start()
            reranked_chunks = await self.rerank_candidates_if_enabled(
                payload,
                candidates,
                rag_plan,
            )
            metrics["rerank_ms"] = elapsed_ms(rerank_started)
            metrics["hit_count"] = len(reranked_chunks)

            refusal_decision = self.rag_evidence_policy.evaluate(
                kb_id=payload.kb_id,
                rag_plan=rag_plan,
                chunks=reranked_chunks,
            )
            if refusal_decision.should_refuse:
                context_started = perf_start()
                search_context = self._build_refusal_search_context(
                    payload=payload,
                    chunks=reranked_chunks,
                    decision=refusal_decision,
                )
                metrics["context_build_ms"] = elapsed_ms(context_started)
                search_context = self._with_rag_metrics(search_context, metrics)
                set_span_attributes(
                    span,
                    {
                        "rag.refusal": True,
                        "rag.refusal_reason": refusal_decision.reason,
                        "rag.hit_count": len(reranked_chunks),
                        "rag.planner.used": planner_used,
                        "rag.planner.should_use_rag": rag_plan.should_use_rag,
                        "rag.planner.retrieval_mode": rag_plan.retrieval_mode,
                    },
                )
                return PreparedGenerationContext(
                    assembled_prompt=None,
                    search_context=search_context,
                    refusal_decision=refusal_decision,
                )

            context_started = perf_start()
            prepared_context = self.chat_context_builder.build_from_chunks(
                history_messages=payload.conversation_history,
                current_query=payload.query_text,
                kb_id=payload.kb_id,
                rag_chunks=reranked_chunks,
                context_state=payload.context_state,
            )
            metrics["context_build_ms"] = elapsed_ms(context_started)
            search_context = self._with_rag_metrics(
                prepared_context.search_context,
                metrics,
            )
            set_span_attributes(
                span,
                {
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
                    "chat.prompt.tokens_input": prepared_context.assembled_prompt.total_tokens,
                    "chat.prompt.message_count": len(
                        prepared_context.assembled_prompt.messages
                    ),
                    "chat.prompt.uses_rag": prepared_context.search_context is not None,
                },
            )
            return PreparedGenerationContext(
                assembled_prompt=prepared_context.assembled_prompt,
                search_context=search_context,
            )

    async def build_rag_plan(
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

    async def retrieve_rag_candidates(
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

    async def rerank_candidates_if_enabled(
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
        if self.rag_service is None:
            return candidates[:limit]
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
                async with llm_concurrency_slot(
                    {
                        "chat.session_id": payload.session_id,
                        "rag.kb_id": payload.kb_id,
                        "rag.rerank": True,
                    }
                ):
                    reranked = await self.rag_service.rerank(
                        query_text=payload.query_text,
                        candidates=candidates,
                        top_k=limit,
                    )
                set_span_attributes(
                    span,
                    {
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

    @staticmethod
    def _with_rag_metrics(
        search_context: dict | None,
        metrics: dict[str, object],
    ) -> dict | None:
        if search_context is None:
            return None
        return merge_metrics(search_context, metrics)
