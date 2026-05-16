"""RAG evidence policy unit tests.

职责：验证 RAGEvidencePolicy 的相关性分数判断和拒绝/放行行为；边界：使用 monkeypatch 固定配置，不依赖真实 LLM；副作用：无。
"""

import pytest

from backend.services.rag_evidence_policy import RAGEvidencePolicy
from backend.services.rag_planning_service import RAGExecutionPlan


def test_hybrid_retrieval_raises_on_low_relevance_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_REFUSAL_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[{"score": 0.2}],
    )

    assert decision.should_refuse is True
    assert decision.reason == "RAG 相关性分数不足"


def test_hybrid_retrieval_passes_on_sufficient_relevance_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_REFUSAL_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_HIT_COUNT",
        1,
    )
    monkeypatch.setattr(
        "backend.services.rag_evidence_policy.ai_settings.RAG_MIN_RELEVANCE_SCORE",
        0.5,
    )
    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=4,
        use_rerank=False,
        candidate_count=20,
        rerank_top_k=4,
    )

    decision = RAGEvidencePolicy().evaluate(
        kb_id=object(),
        rag_plan=plan,
        chunks=[{"score": 0.7}],
    )

    assert decision.should_refuse is False
    assert decision.reason == "RAG 证据充足"
