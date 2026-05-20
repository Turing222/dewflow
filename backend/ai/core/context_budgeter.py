"""Context budgeter.

职责：显式管理 token 预算，按 block 优先级分配，并提供最终兜底检查。
边界：不调用 LLM，不 IO，只做纯计算。
"""

import logging
from dataclasses import dataclass

from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.models.schemas.chat.dto import ConversationMessage

logger = logging.getLogger(__name__)

# Block 优先级常量，数字越小越优先保留
PRIORITY_QUERY = 0
PRIORITY_SYSTEM = 1
PRIORITY_RAG_CHUNKS = 2
PRIORITY_HISTORY = 3
PRIORITY_BRIDGE = 4


@dataclass
class BudgetBlock:
    """单个上下文的 token 预算块。"""

    name: str
    priority: int = PRIORITY_HISTORY
    content: str = ""
    token_estimate: int = 0
    allocated: int = 0
    compressible: bool = False
    required: bool = False


class ContextBudgeter:
    """按优先级分配 token 预算，并提供最终兜底检查。"""

    def __init__(
        self,
        max_context_tokens: int | None = None,
        reserved_response_tokens: int | None = None,
        model_name: str | None = None,
    ) -> None:
        self.max_context_tokens = max_context_tokens or settings.LLM_MAX_CONTEXT_TOKENS
        self.reserved_response_tokens = (
            reserved_response_tokens or settings.LLM_RESERVED_RESPONSE_TOKENS
        )
        self.model_name = model_name or get_llm_model_config().resolve_profile().model

    @property
    def total_budget(self) -> int:
        """可用于 context 的 token 上限。"""
        return max(0, self.max_context_tokens - self.reserved_response_tokens)

    def allocate(self, blocks: list[BudgetBlock]) -> list[BudgetBlock]:
        """按优先级分配 budget。

        策略:
        1. required blocks 先占
        2. 非 required blocks 按 priority 升序分配
        3. 不足时 compressible block 被标记为需压缩
        4. 仍不足时低优先级 block 分配 0
        """
        remaining = self.total_budget
        result: list[BudgetBlock] = []

        for block in blocks:
            if not block.token_estimate:
                block.token_estimate = (len(block.content) + 3) // 4
            result.append(block)

        for block in result:
            if block.required:
                take = min(block.token_estimate, remaining)
                block.allocated = take
                remaining -= take

        sorted_rest = sorted(
            [b for b in result if not b.required],
            key=lambda b: (b.priority, b.token_estimate),
        )

        for block in sorted_rest:
            if remaining <= 0:
                block.allocated = 0
            elif block.token_estimate <= remaining:
                block.allocated = block.token_estimate
                remaining -= block.token_estimate
            elif block.compressible:
                block.allocated = max(0, remaining)
                remaining = 0
            else:
                block.allocated = 0

        return result

    def validate(
        self, messages: list[ConversationMessage], actual_tokens: int | None = None
    ) -> tuple[bool, int]:
        """最终兜底检查，(ok, actual_tokens)。"""
        if actual_tokens is None:
            from backend.ai.core.token_counter import count_messages_tokens

            actual_tokens = count_messages_tokens(messages, self.model_name)
        ok = actual_tokens <= self.total_budget
        if not ok:
            logger.warning(
                "Context 超限: actual=%d budget=%d", actual_tokens, self.total_budget
            )
        return ok, actual_tokens
