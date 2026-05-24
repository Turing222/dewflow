"""RAG planning service unit tests.

职责：验证 RAGExecutionPlan 的值钳位和 RAGPlanningService 的模型构建与降级行为；边界：使用 FakePlanner 和 monkeypatch，不连接真实 LLM；副作用：无。
"""

import uuid

import pytest
from pydantic import ValidationError

from backend.services.rag_planning_service import (
    RAG_PLANNER_FALLBACK_REASON,
    RAGExecutionPlan,
    RAGPlanningService,
)


class FakePlanner(RAGPlanningService):
    def __init__(self, output: object) -> None:
        super().__init__()
        self.output = output

    async def _run_agent(
        self, *, query_text: str, conversation_history: list[object], **_: object
    ) -> object:
        if isinstance(self.output, BaseException):
            raise self.output
        return self.output


class RecordingPlanner(FakePlanner):
    def __init__(self, output: object) -> None:
        super().__init__(output)
        self.calls: list[dict[str, object]] = []

    async def _run_agent(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return await super()._run_agent(**kwargs)


def test_rag_execution_plan_clamps_values_to_config_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_TOP_K",
        4,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_RERANK_CANDIDATE_COUNT",
        20,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_RERANK_TOP_K",
        3,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.EXTERNAL_CONTEXT_TOP_K",
        4,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.EXTERNAL_CONTEXT_ENABLED",
        True,
    )

    plan = RAGExecutionPlan(
        should_use_rag=True,
        retrieval_mode="hybrid",
        top_k=99,
        use_rerank=True,
        candidate_count=99,
        rerank_top_k=99,
        should_use_external_context=True,
        external_sources=["web"],
        external_top_k=99,
    ).clamped()

    assert plan.top_k == 4
    assert plan.candidate_count == 20
    assert plan.rerank_top_k == 3
    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]
    assert plan.external_top_k == 4


def test_from_settings_enables_external_context_when_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.EXTERNAL_CONTEXT_ENABLED",
        True,
    )

    plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="test query",
        external_context_allowed=True,
    )

    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]


def test_from_settings_disables_external_context_when_not_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.EXTERNAL_CONTEXT_ENABLED",
        True,
    )

    plan = RAGExecutionPlan.from_settings(
        has_kb=True,
        query_text="test query",
        external_context_allowed=False,
    )

    assert plan.should_use_external_context is False
    assert plan.external_sources == []


def test_rag_planning_service_builds_plan_via_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_create_model(
        *, profile: object, api_key: str, max_retries: object = None
    ) -> str:
        captured["profile"] = profile
        captured["api_key"] = api_key
        captured["max_retries"] = max_retries
        return "model"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "planner-key")
    monkeypatch.setattr(
        "backend.services.rag_planning_service.create_pydantic_ai_model",
        fake_create_model,
    )

    model = RAGPlanningService(provider="deepseek")._create_model()

    assert model == "model"
    assert captured["profile"].provider == "deepseek"
    assert captured["api_key"] == "planner-key"
    assert captured["max_retries"] is None


@pytest.mark.asyncio
async def test_rag_planning_service_returns_fallback_on_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )
    invalid_output = ValidationError.from_exception_data(
        "RAGExecutionPlan",
        [
            {
                "type": "missing",
                "loc": ("should_use_rag",),
                "input": {},
            }
        ],
    )
    planner = FakePlanner(invalid_output)

    plan = await planner.plan(
        query_text="查询知识库",
        conversation_history=[],
        kb_id=uuid.uuid4(),
    )

    assert plan.should_use_rag is True
    assert plan.reason == RAG_PLANNER_FALLBACK_REASON


@pytest.mark.asyncio
async def test_rag_planning_service_runs_without_kb_when_external_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.RAG_PLANNER_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "backend.services.rag_planning_service.ai_settings.EXTERNAL_CONTEXT_ENABLED",
        True,
    )
    planner = RecordingPlanner(
        RAGExecutionPlan(
            should_use_rag=False,
            should_use_external_context=True,
            external_sources=["web"],
        )
    )

    plan = await planner.plan(
        query_text="今天的公开信息",
        conversation_history=[],
        kb_id=None,
        enable_external_context=True,
    )

    assert plan.should_use_external_context is True
    assert plan.external_sources == ["web"]
    assert planner.calls[0]["has_kb"] is False
    assert planner.calls[0]["enable_external_context"] is True
