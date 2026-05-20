"""Message compressor.

职责：压缩超长单条消息和批量消息，支持截断和可选的 LLM 摘要。
边界：本模块默认不调用 LLM；LLM summarizer 由调用方注入。
失败处理：LLM summarizer 失败时自动回退到 truncate。
"""

import logging
from collections.abc import Awaitable, Callable

from backend.ai.core.token_counter import count_messages_tokens
from backend.models.schemas.chat.dto import ConversationMessage

logger = logging.getLogger(__name__)

_DEFAULT_TRUNCATION_THRESHOLD_CHARS = 2000
_DEFAULT_TAIL_RATIO = 0.3


class MessageCompressor:
    """单条/批量消息压缩，默认截断，可选 LLM 摘要。"""

    def __init__(
        self,
        truncation_threshold_chars: int = _DEFAULT_TRUNCATION_THRESHOLD_CHARS,
        summarizer: Callable[[str, int], Awaitable[str]] | None = None,
    ) -> None:
        self._threshold = truncation_threshold_chars
        self._summarizer = summarizer

    def compress(self, content: str, target_chars: int) -> str:
        """截断单条消息到 target_chars，在自然边界断开。"""
        if len(content) <= target_chars:
            return content
        return self.truncate(content, target_chars)

    async def compress_async(self, content: str, target_chars: int) -> str:
        """异步压缩：有 summarizer 时走 LLM 摘要，否则截断。"""
        if len(content) <= target_chars:
            return content
        if self._summarizer is not None:
            try:
                return await self._summarizer(content, target_chars)
            except Exception:
                logger.warning(
                    "LLM 摘要失败，回退到截断 (target_chars=%d)", target_chars
                )
        return self.truncate(content, target_chars)

    async def compress_batch(
        self,
        messages: list[ConversationMessage],
        budget_tokens: int,
        model: str,
    ) -> list[ConversationMessage]:
        """批量压缩：舍弃最旧消息直到满足 budget，最后压缩保留下来的第一条。

        从最新到最旧累积 token；超出时保留已累积的消息，
        更旧的丢弃。如果连一条都放不下，压缩最新的一条。
        """
        if not messages:
            return []

        if count_messages_tokens(messages, model) <= budget_tokens:
            return list(messages)

        kept: list[ConversationMessage] = []
        for msg in reversed(messages):
            trial = [msg] + kept
            if count_messages_tokens(trial, model) <= budget_tokens:
                kept.insert(0, msg)
            else:
                break

        if kept:
            return kept

        newest = messages[-1]
        role_overhead = 4 + len(newest["role"]) // 3
        target_content_tokens = max(10, budget_tokens - role_overhead - 2)
        target_chars = target_content_tokens * 3
        compressed = await self.compress_async(newest["content"], target_chars)
        return [{"role": newest["role"], "content": compressed}]

    @staticmethod
    def truncate(content: str, target_chars: int) -> str:
        """保留首部到 target_chars，在自然边界（。. \\n）断开。"""
        if len(content) <= target_chars:
            return content
        if target_chars <= 0:
            return ""

        truncated = content[:target_chars]
        for boundary in ("。", "\n\n", ". ", "\n", ".", " "):
            pos = truncated.rfind(boundary)
            if pos > target_chars * 0.5:
                return truncated[: pos + len(boundary)]
        return truncated

    @staticmethod
    def truncate_head_tail(content: str, head_chars: int, tail_chars: int) -> str:
        """保留首尾的截断，保留中间省略标记。"""
        head_chars = max(0, head_chars)
        tail_chars = max(0, tail_chars)
        if len(content) <= head_chars + tail_chars:
            return content
        if tail_chars <= 0:
            return content[:head_chars] + "\n..."
        if head_chars <= 0:
            return "...\n" + content[-tail_chars:]
        head = content[:head_chars]
        tail = content[-tail_chars:]
        return f"{head}\n...\n{tail}"
