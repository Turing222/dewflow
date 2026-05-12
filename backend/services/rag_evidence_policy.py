"""RAG evidence refusal policy.

职责：根据检索命中与 RAG 计划判断知识库证据是否足以回答。
边界：本模块不执行检索、不调用 LLM、不组装 Prompt；只返回可观测的拒答决策。
"""

from dataclasses import dataclass
from typing import Any

from backend.config.ai_settings import ai_settings
from backend.services.rag_planning_service import RAGExecutionPlan


@dataclass(frozen=True)
class RAGEvidenceDecision:
    """RAG 证据充足性判断结果。"""

    should_refuse: bool
    reason: str
    hit_count: int
    best_score: float | None = None
    best_rerank_score: float | None = None
    policy_version: int = 1

    def to_metadata(self) -> dict[str, object]:
        return {
            "rag_refusal": self.should_refuse,
            "reason": self.reason,
            "hit_count": self.hit_count,
            "best_score": self.best_score,
            "best_rerank_score": self.best_rerank_score,
            "policy_version": self.policy_version,
        }


class RAGEvidencePolicy:
    """轻量 RAG 证据门禁。"""

    def evaluate(
        self,
        *,
        kb_id: object | None,
        rag_plan: RAGExecutionPlan,
        chunks: list[dict[str, Any]],
    ) -> RAGEvidenceDecision:
        hit_count = len(chunks)
        best_score = self._max_numeric(chunks, "score")
        best_rerank_score = self._max_numeric(chunks, "rerank_score")

        if not ai_settings.RAG_REFUSAL_ENABLED:
            return self._allow("RAG 拒答策略未启用", hit_count, best_score, best_rerank_score)
        if kb_id is None or not rag_plan.should_use_rag:
            return self._allow("当前问题不需要知识库证据", hit_count, best_score, best_rerank_score)
        if hit_count < ai_settings.RAG_MIN_HIT_COUNT:
            return self._refuse("RAG 命中数量不足", hit_count, best_score, best_rerank_score)
        if best_rerank_score is not None:
            if best_rerank_score < ai_settings.RAG_MIN_RERANK_SCORE:
                return self._refuse("RAG rerank 相关性不足", hit_count, best_score, best_rerank_score)
            return self._allow("RAG rerank 证据充足", hit_count, best_score, best_rerank_score)
        if rag_plan.retrieval_mode == "hybrid":
            return self._allow("RAG hybrid 命中数量充足", hit_count, best_score, best_rerank_score)
        if best_score is None or best_score < ai_settings.RAG_MIN_RELEVANCE_SCORE:
            return self._refuse("RAG 相关性分数不足", hit_count, best_score, best_rerank_score)
        return self._allow("RAG 证据充足", hit_count, best_score, best_rerank_score)

    @staticmethod
    def _max_numeric(chunks: list[dict[str, Any]], key: str) -> float | None:
        values: list[float] = []
        for chunk in chunks:
            value = chunk.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return max(values) if values else None

    @staticmethod
    def _allow(
        reason: str,
        hit_count: int,
        best_score: float | None,
        best_rerank_score: float | None,
    ) -> RAGEvidenceDecision:
        return RAGEvidenceDecision(False, reason, hit_count, best_score, best_rerank_score)

    @staticmethod
    def _refuse(
        reason: str,
        hit_count: int,
        best_score: float | None,
        best_rerank_score: float | None,
    ) -> RAGEvidenceDecision:
        return RAGEvidenceDecision(True, reason, hit_count, best_score, best_rerank_score)
