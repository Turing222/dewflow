"""Prompt manager.

职责：渲染 system prompt，拼接最终的 messages 列表。
边界：本模块不再负责历史窗口选择和 token 预算裁剪——
     这些职责已移交给 LiveWindowBuilder 和 ContextBudgeter。
"""

import logging
from dataclasses import dataclass, field

from jinja2 import Template

from backend.ai.core.prompt_resolver import get_prompt_resolver
from backend.ai.core.prompt_templates import render_system_prompt
from backend.ai.core.token_counter import count_messages_tokens
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.models.schemas.chat.dto import ConversationMessage

logger = logging.getLogger(__name__)


@dataclass
class AssembledPrompt:
    """Prompt 组装结果和预算统计。"""

    messages: list[ConversationMessage] = field(default_factory=list)
    total_tokens: int = 0
    history_rounds_used: int = 0
    truncated: bool = False


class PromptManager:
    """Jinja2 驱动的 Prompt 组装器。

    assemble() 现在只负责渲染 system prompt 和拼接 messages。
    历史窗口选择逻辑已移到 LiveWindowBuilder。
    """

    def __init__(
        self,
        system_template: Template | None = None,
        template_name: str = "default_system",
        template_vars: dict | None = None,
        max_context_tokens: int | None = None,
        max_history_rounds: int | None = None,
        reserved_response_tokens: int | None = None,
        model_name: str | None = None,
    ):
        self.system_template = system_template
        self.template_name = template_name
        self.template_vars = template_vars or {}
        self.max_context_tokens = max_context_tokens or settings.LLM_MAX_CONTEXT_TOKENS
        self.max_history_rounds = max_history_rounds or settings.LLM_MAX_HISTORY_ROUNDS
        self.reserved_response_tokens = (
            reserved_response_tokens or settings.LLM_RESERVED_RESPONSE_TOKENS
        )
        self.model_name = model_name or get_llm_model_config().resolve_profile().model

    def assemble(
        self,
        history: list[ConversationMessage],
        current_query: str,
        extra_vars: dict | None = None,
    ) -> AssembledPrompt:
        """渲染 system prompt 并拼接 messages。

        history 应为调用方已经过 LiveWindowBuilder 处理后的列表。
        本方法只做拼接，不做 token 预算裁剪。
        """
        merged_vars = {**self.template_vars, **(extra_vars or {})}
        system_template = self.system_template or get_prompt_resolver().get_template(
            self.template_name
        )
        system_content = render_system_prompt(template=system_template, **merged_vars)

        messages: list[ConversationMessage] = []
        if system_content.strip():
            messages.append({"role": "system", "content": system_content})
        messages.extend(history)
        messages.append({"role": "user", "content": current_query})

        total_tokens = count_messages_tokens(messages, self.model_name)
        rounds = self._group_into_rounds(history)

        token_budget = self.max_context_tokens - self.reserved_response_tokens

        result = AssembledPrompt(
            messages=messages,
            total_tokens=total_tokens,
            history_rounds_used=len(rounds),
            truncated=False,
        )

        total = result.total_tokens
        logger.info(
            "Prompt 组装完成: total_tokens=%d, history_rounds=%d, budget=%d",
            total,
            result.history_rounds_used,
            token_budget,
        )

        return result

    @staticmethod
    def _group_into_rounds(
        history: list[ConversationMessage],
    ) -> list[list[ConversationMessage]]:
        """按 user 消息边界拆分历史，兼容连续同角色消息。"""
        if not history:
            return []

        rounds: list[list[ConversationMessage]] = []
        current_round: list[ConversationMessage] = []

        for msg in history:
            role = msg["role"]
            if role == "system":
                continue
            if role == "user" and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(msg)

        if current_round:
            rounds.append(current_round)

        return rounds
