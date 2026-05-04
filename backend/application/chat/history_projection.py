"""Lightweight chat history projection helpers for Web workflows."""

from typing import Any, cast

from backend.models.schemas.chat_schema import ChatMessageRole, ConversationMessage


def history_to_conversation_messages(
    messages: list[dict[str, Any] | Any],
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
            history.append(
                {"role": cast(ChatMessageRole, role), "content": str(content)}
            )
    return history
