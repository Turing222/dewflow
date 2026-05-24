"""RAG planning service.

职责：在 Worker 检索前生成结构化 RAG 执行计划，约束检索策略与 rerank 参数。
边界：本模块不执行检索、不组装 Prompt；失败时只返回可降级的默认计划。
副作用：启用后会调用 LLM planner，并把模型输出校验为 RAGExecutionPlan。
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.ai.providers.llm.pydantic_ai_models import create_pydantic_ai_model
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.models.schemas.chat.context_routing import (
    ContextMode,
    ContextSource,
    is_external_context_allowed,
    resolve_context_mode,
    source_selected,
)
from backend.models.schemas.chat.dto import ConversationMessage
from backend.observability.trace_utils import set_span_attributes, trace_span

logger = logging.getLogger(__name__)

RAGRetrievalMode = Literal["vector", "fulltext", "hybrid"]
ExternalContextSource = Literal["web"]
RAG_PLANNER_FALLBACK_REASON = "RAG planner 降级为默认计划"


class RAGExecutionPlan(BaseModel):
    """RAG 检索执行计划。"""

    context_mode: ContextMode = "auto"
    selected_sources: list[ContextSource] = Field(default_factory=list)
    should_use_rag: bool
    retrieval_mode: RAGRetrievalMode = "vector"
    top_k: int = Field(default=4, ge=1)
    use_rerank: bool = False
    candidate_count: int = Field(default=20, ge=1)
    rerank_top_k: int = Field(default=4, ge=1)
    should_use_external_context: bool = False
    external_sources: list[ExternalContextSource] = Field(default_factory=list)
    external_top_k: int = Field(default=4, ge=1)
    reason: str = ""

    @model_validator(mode="after")
    def sync_context_sources(self) -> "RAGExecutionPlan":
        sources = list(dict.fromkeys(self.selected_sources))
        if self.should_use_rag and "kb" not in sources:
            sources.append("kb")
        if (
            self.should_use_external_context or self.external_sources
        ) and "web" not in sources:
            sources.append("web")
        if self.context_mode == "off":
            sources = []
        elif self.context_mode == "kb_only":
            sources = [source for source in sources if source == "kb"]
        elif self.context_mode == "web_only":
            sources = [source for source in sources if source == "web"]
        self.selected_sources = sources
        self.should_use_rag = "kb" in sources
        self.should_use_external_context = "web" in sources
        self.external_sources = ["web"] if "web" in sources else []
        return self

    @classmethod
    def from_settings(
        cls,
        *,
        has_kb: bool,
        query_text: str,
        external_context_allowed: bool = False,
        context_mode: ContextMode | None = None,
        reason: str = "使用默认 RAG 配置",
    ) -> "RAGExecutionPlan":
        resolved_mode = resolve_context_mode(
            context_mode=context_mode,
            enable_external_context=external_context_allowed,
        )
        has_query = bool(query_text.strip())
        should_use_rag = has_kb and has_query and resolved_mode in {"auto", "kb_only"}
        should_use_external_context = (
            has_query
            and resolved_mode in {"auto", "web_only"}
            and external_context_allowed
            and ai_settings.EXTERNAL_CONTEXT_ENABLED
        )
        selected_sources: list[ContextSource] = []
        if should_use_rag:
            selected_sources.append("kb")
        if should_use_external_context:
            selected_sources.append("web")
        return cls(
            context_mode=resolved_mode,
            selected_sources=selected_sources,
            should_use_rag=should_use_rag,
            retrieval_mode="hybrid" if ai_settings.RAG_RERANK_ENABLED else "vector",
            top_k=max(1, ai_settings.RAG_TOP_K),
            use_rerank=ai_settings.RAG_RERANK_ENABLED and should_use_rag,
            candidate_count=ai_settings.RAG_RERANK_CANDIDATE_COUNT,
            rerank_top_k=ai_settings.RAG_RERANK_TOP_K,
            should_use_external_context=should_use_external_context,
            external_sources=["web"] if should_use_external_context else [],
            external_top_k=ai_settings.EXTERNAL_CONTEXT_TOP_K,
            reason=reason,
        ).clamped()

    def clamped(self) -> "RAGExecutionPlan":
        top_k = _clamp(self.top_k, 1, max(1, ai_settings.RAG_TOP_K))
        candidate_count = _clamp(
            self.candidate_count,
            1,
            ai_settings.RAG_RERANK_CANDIDATE_COUNT,
        )
        rerank_top_k = _clamp(
            self.rerank_top_k,
            1,
            ai_settings.RAG_RERANK_TOP_K,
        )
        external_top_k = _clamp(
            self.external_top_k,
            1,
            ai_settings.EXTERNAL_CONTEXT_TOP_K,
        )
        selected_sources = [
            source
            for source in dict.fromkeys(self.selected_sources)
            if source in ("kb", "web", "skill", "mcp")
        ]
        should_use_rag = source_selected(selected_sources, "kb")
        should_use_external_context = source_selected(selected_sources, "web")
        external_sources = ["web"] if should_use_external_context else []
        return self.model_copy(
            update={
                "top_k": top_k,
                "candidate_count": candidate_count,
                "rerank_top_k": rerank_top_k,
                "use_rerank": self.use_rerank and should_use_rag,
                "selected_sources": selected_sources,
                "should_use_rag": should_use_rag,
                "should_use_external_context": should_use_external_context,
                "external_sources": external_sources,
                "external_top_k": external_top_k,
            }
        )


class RAGPlanningService:
    """基于 Pydantic AI 的 RAG 计划生成器。"""

    def __init__(self, *, provider: str | None = None) -> None:
        self.provider = provider
        self._agent: Any = None

    async def plan(
        self,
        *,
        query_text: str,
        conversation_history: list[ConversationMessage],
        kb_id: uuid.UUID | None,
        enable_external_context: bool = False,
        context_mode: ContextMode | None = None,
    ) -> RAGExecutionPlan:
        resolved_mode = resolve_context_mode(
            context_mode=context_mode,
            enable_external_context=enable_external_context,
        )
        external_context_allowed = is_external_context_allowed(
            context_mode=context_mode,
            enable_external_context=enable_external_context,
            external_context_enabled=ai_settings.EXTERNAL_CONTEXT_ENABLED,
        )
        default_plan = RAGExecutionPlan.from_settings(
            has_kb=kb_id is not None,
            query_text=query_text,
            external_context_allowed=external_context_allowed,
            context_mode=resolved_mode,
        )
        if (
            not query_text.strip()
            or not ai_settings.RAG_PLANNER_ENABLED
            or resolved_mode == "off"
            or (kb_id is None and not external_context_allowed)
        ):
            return default_plan

        try:
            with trace_span(
                "rag.planner.generate",
                {
                    "rag.kb_id": kb_id,
                    "rag.planner.enabled": True,
                    "rag.query.char_count": len(query_text),
                },
            ) as span:
                generated = await asyncio.wait_for(
                    self._run_agent(
                        query_text=query_text,
                        conversation_history=conversation_history,
                        has_kb=kb_id is not None,
                        enable_external_context=external_context_allowed,
                        context_mode=resolved_mode,
                    ),
                    timeout=ai_settings.RAG_PLANNER_TIMEOUT_SECONDS,
                )
                plan = generated.clamped()
                set_span_attributes(span, _trace_attrs(plan, used=True, fallback=False))
                return plan
        except Exception as exc:
            logger.warning("RAG planner 失败，降级为默认计划: %s", exc)
            return RAGExecutionPlan.from_settings(
                has_kb=kb_id is not None,
                query_text=query_text,
                external_context_allowed=external_context_allowed,
                context_mode=resolved_mode,
                reason=RAG_PLANNER_FALLBACK_REASON,
            )

    def _ensure_agent(self) -> Any:
        if self._agent is None:
            try:
                from pydantic_ai import Agent
            except ImportError as exc:
                raise RuntimeError("pydantic-ai 未安装") from exc

            self._agent = Agent(
                self._create_model(),
                output_type=RAGExecutionPlan,
                instructions=_PLANNER_INSTRUCTIONS,
                instrument=True,
                name="rag_planner",
            )
        return self._agent

    async def _run_agent(
        self,
        *,
        query_text: str,
        conversation_history: list[ConversationMessage],
        has_kb: bool,
        enable_external_context: bool,
        context_mode: ContextMode,
    ) -> RAGExecutionPlan:
        agent = self._ensure_agent()
        result = await agent.run(
            _build_planner_prompt(
                query_text=query_text,
                conversation_history=conversation_history,
                has_kb=has_kb,
                enable_external_context=enable_external_context,
                context_mode=context_mode,
            )
        )
        output = result.output
        if isinstance(output, RAGExecutionPlan):
            return output
        return RAGExecutionPlan.model_validate(output)

    def _create_model(self):
        profile = get_llm_model_config().resolve_profile(
            self.provider
            or ai_settings.RAG_PLANNER_PROVIDER
            or ai_settings.LLM_PROVIDER
        )
        return create_pydantic_ai_model(
            profile=profile, api_key=profile.resolve_api_key()
        )


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def _trace_attrs(
    plan: RAGExecutionPlan,
    *,
    used: bool,
    fallback: bool,
) -> dict[str, object]:
    return {
        "rag.planner.used": used,
        "rag.planner.should_use_rag": plan.should_use_rag,
        "rag.planner.retrieval_mode": plan.retrieval_mode,
        "rag.planner.use_rerank": plan.use_rerank,
        "context.mode": plan.context_mode,
        "context.selected_sources": ",".join(plan.selected_sources),
        "external_context.should_use": plan.should_use_external_context,
        "external_context.sources": ",".join(plan.external_sources),
        "rag.planner.fallback": fallback,
    }


def _build_planner_prompt(
    *,
    query_text: str,
    conversation_history: list[ConversationMessage],
    has_kb: bool,
    enable_external_context: bool,
    context_mode: ContextMode,
) -> str:
    recent_history = [
        _serialize_history_message(message) for message in conversation_history[-6:]
    ]
    return "\n".join(
        [
            "请判断当前用户问题是否需要检索知识库，并给出 RAG 执行计划。",
            "只根据问题与最近对话判断，不要回答用户问题。",
            f"上下文路由模式: {context_mode}",
            f"当前会话是否有关联知识库: {has_kb}",
            f"用户是否允许外部上下文检索: {enable_external_context}",
            "",
            f"当前问题: {query_text}",
            "最近对话:",
            json.dumps(recent_history, ensure_ascii=False),
        ]
    )


def _serialize_history_message(message: ConversationMessage) -> dict[str, str]:
    return {
        "role": str(message.get("role") or ""),
        "content": str(message.get("content") or ""),
    }


_PLANNER_INSTRUCTIONS = """你是 RAG 检索规划器。
返回结构化计划：
- context_mode: 原样使用输入中的上下文路由模式。
- selected_sources: 选择需要执行的上下文来源；v1 只可实际选择 kb/web，skill/mcp 仅预留。
- should_use_rag: 用户问题需要知识库事实、文档内容、项目资料时为 true；闲聊、写作泛化、无需外部资料时为 false。
- retrieval_mode: 精确关键词或文件名查询用 fulltext；语义查询用 vector；不确定或需要兼顾时用 hybrid。
- top_k: 普通检索数量。
- use_rerank: 需要从较多候选中精选相关片段时为 true。
- candidate_count: rerank 候选数量。
- rerank_top_k: rerank 后保留数量。
- should_use_external_context: 仅当用户允许外部上下文且问题需要最新信息、公开网页事实、知识库缺口补充时为 true。
- external_sources: 目前只允许 ["web"]；不需要外部上下文时返回 []。
- external_top_k: 外部上下文检索数量。
- reason: 简短中文原因。
约束：
- context_mode=off 时 selected_sources 必须为 []。
- context_mode=kb_only 时 selected_sources 最多包含 kb。
- context_mode=web_only 时 selected_sources 最多包含 web。
- context_mode=auto 时按问题需要选择 kb、web 或两者。
"""
