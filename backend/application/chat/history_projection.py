"""Lightweight chat history projection helpers for Web workflows."""

from collections.abc import Sequence
from typing import Any

from backend.models.schemas.chat.dto import ConversationMessage


def history_to_conversation_messages(
    messages: Sequence[Any],
) -> list[ConversationMessage]:
    """Keep only user/assistant messages needed by worker prompt assembly."""
    history: list[ConversationMessage] = []
    for msg in messages:
        if isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content")
        else:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", None)
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": str(content)})
    return history
