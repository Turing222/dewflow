"""Live window builder.

职责：在给定 token budget 内构建最优历史窗口——选择保留原文的最近轮次，
     为旧轮次生成桥接摘要，必要时压缩超长单条消息。
边界：默认不调用 LLM；LLM 摘要由注入的 MessageCompressor 统一管理。
"""

import logging
from dataclasses import dataclass, field

from backend.ai.core.message_compressor import MessageCompressor
from backend.ai.core.token_counter import count_messages_tokens
from backend.config.settings import settings
from backend.models.schemas.chat.dto import ConversationMessage

logger = logging.getLogger(__name__)


@dataclass
class LiveWindowResult:
    """历史窗口构建结果。"""

    exact_messages: list[ConversationMessage] = field(default_factory=list)
    bridge_summary: str = ""
    overflow_compressed: bool = False


class LiveWindowBuilder:
    """在给定的 history token budget 内构建最优历史窗口。"""

    def __init__(
        self,
        recent_rounds: int | None = None,
        snippet_chars: int | None = None,
        summary_max_chars: int | None = None,
        message_compressor: MessageCompressor | None = None,
    ) -> None:
        self.recent_rounds = (
            recent_rounds
            if recent_rounds is not None
            else settings.CHAT_MEMORY_RECENT_ROUNDS
        )
        self.snippet_chars = (
            snippet_chars
            if snippet_chars is not None
            else max(20, settings.CHAT_MEMORY_SNIPPET_CHARS)
        )
        self.summary_max_chars = (
            summary_max_chars
            if summary_max_chars is not None
            else max(1, settings.CHAT_MEMORY_SUMMARY_MAX_CHARS)
        )
        self.message_compressor = message_compressor or MessageCompressor()

    def build(
        self,
        history: list[ConversationMessage],
        current_query: str,
        budget_tokens: int,
        model: str,
    ) -> LiveWindowResult:
        """主入口：在 budget 内构建历史窗口。

        1. 排除与 current_query 重复的最后一条 user 消息
        2. 按 user 边界分组为 rounds
        3. 保留最近 recent_rounds 轮作为 exact_messages
        4. 超 budget 时压缩/丢弃最旧的 exact_messages
        5. 旧轮次生成 bridge_summary
        """
        if not history:
            return LiveWindowResult()

        history = self._exclude_latest_query(history, current_query)
        if not history:
            return LiveWindowResult()

        rounds = self._group_history_rounds(history)
        if not rounds:
            return LiveWindowResult()

        recent_count = max(0, self.recent_rounds)
        if recent_count <= 0:
            older_rounds = rounds
            kept_rounds: list[list[ConversationMessage]] = []
        elif len(rounds) > recent_count:
            older_rounds = rounds[:-recent_count]
            kept_rounds = rounds[-recent_count:]
        else:
            older_rounds = []
            kept_rounds = rounds

        exact_messages = [msg for rnd in kept_rounds for msg in rnd]
        overflow_compressed = False

        if budget_tokens <= 0:
            return LiveWindowResult(
                exact_messages=[],
                bridge_summary=self._build_rounds_summary(older_rounds),
                overflow_compressed=bool(exact_messages),
            )

        if budget_tokens > 0 and exact_messages:
            current_tokens = count_messages_tokens(exact_messages, model)
            if current_tokens > budget_tokens:
                overflow_compressed = True
                exact_messages = self._fit_messages(
                    exact_messages, budget_tokens, model
                )

        bridge_summary = self._build_rounds_summary(older_rounds)

        return LiveWindowResult(
            exact_messages=exact_messages,
            bridge_summary=bridge_summary,
            overflow_compressed=overflow_compressed,
        )

    # ── history window fitting ──────────────────────────────────────

    def _fit_messages(
        self,
        messages: list[ConversationMessage],
        budget_tokens: int,
        model: str,
    ) -> list[ConversationMessage]:
        """在 budget 内保留尽可能多的最新消息，必要时丢弃最旧的。

        这是一个同步方法，只做丢弃/截断，不做异步 LLM 压缩。
        如需 LLM 压缩应在调用方使用 MessageCompressor.compress_batch()。
        """
        kept: list[ConversationMessage] = []
        for msg in reversed(messages):
            trial = [msg] + kept
            if count_messages_tokens(trial, model) <= budget_tokens:
                kept.insert(0, msg)
            else:
                break

        if not kept and messages:
            newest = messages[-1]
            truncated = self.message_compressor.compress(
                newest["content"], max(10, budget_tokens * 2)
            )
            kept = [{"role": newest["role"], "content": truncated}]

        return kept

    # ── round helpers ───────────────────────────────────────────────

    @staticmethod
    def _group_history_rounds(
        history: list[ConversationMessage],
    ) -> list[list[ConversationMessage]]:
        """按 user 消息边界拆分历史为对话轮次。"""
        if not history:
            return []

        rounds: list[list[ConversationMessage]] = []
        current_round: list[ConversationMessage] = []

        for msg in history:
            role = msg["role"]
            if role == "user" and current_round:
                rounds.append(current_round)
                current_round = []
            current_round.append(msg)

        if current_round:
            rounds.append(current_round)

        return rounds

    @staticmethod
    def _exclude_latest_query(
        history: list[ConversationMessage],
        current_query: str,
    ) -> list[ConversationMessage]:
        """如果历史最后一条 user 消息与当前 query 相同，则排除。"""
        if not history:
            return history

        latest = history[-1]
        if latest["role"] != "user":
            return history

        latest_text = " ".join((latest["content"] or "").split())
        query_text = " ".join((current_query or "").split())
        if latest_text and latest_text == query_text:
            return history[:-1]
        return history

    # ── summary ─────────────────────────────────────────────────────

    def _build_rounds_summary(
        self, rounds: list[list[ConversationMessage]]
    ) -> str:
        """为旧轮次生成纯文本摘要（截断拼接，不调用 LLM）。"""
        if not rounds:
            return ""

        snippet_limit = self.snippet_chars
        max_chars = self.summary_max_chars

        lines: list[str] = []
        for round_msgs in rounds:
            user_text = self._normalize_text(
                " ".join(msg["content"] for msg in round_msgs if msg["role"] == "user")
            )
            assistant_text = self._normalize_text(
                " ".join(
                    msg["content"] for msg in round_msgs if msg["role"] == "assistant"
                )
            )
            if not user_text and not assistant_text:
                continue

            user_excerpt = self._truncate_text(user_text, snippet_limit) or "(空)"
            assistant_excerpt = (
                self._truncate_text(assistant_text, snippet_limit) or "(空)"
            )
            lines.append(f"- 用户: {user_excerpt} | 助手: {assistant_excerpt}")

        if not lines:
            return ""

        while lines and len("\n".join(lines)) > max_chars:
            lines.pop(0)

        if not lines:
            return self._truncate_text("", max_chars)

        return "\n".join(lines)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").split())

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 3)]}..."
