"""HTTP Server-Sent Events for chat streaming.

职责：定义 Chat HTTP SSE 层 typed event，并负责序列化为对外兼容的 wire format。
边界：本模块只服务 HTTP 响应；Worker 到 Web 的 Redis 内部事件协议在 application.chat.stream_events。
"""

import json
from typing import Literal, TypedDict


class MetaEvent(TypedDict):
    """Chat stream metadata event."""

    type: Literal["meta"]
    session_id: str
    session_title: str | None
    message_id: str


class ChunkEvent(TypedDict):
    """Chat stream content chunk event."""

    type: Literal["chunk"]
    content: str


class ErrorEvent(TypedDict):
    """Chat stream error event."""

    type: Literal["error"]
    message: str


class DoneEvent(TypedDict):
    """Chat stream completion marker."""

    type: Literal["done"]


SSEEvent = MetaEvent | ChunkEvent | ErrorEvent | DoneEvent


def meta_event(
    *,
    session_id: str,
    session_title: str | None,
    message_id: str,
) -> MetaEvent:
    return {
        "type": "meta",
        "session_id": session_id,
        "session_title": session_title,
        "message_id": message_id,
    }


def chunk_event(content: str) -> ChunkEvent:
    return {"type": "chunk", "content": content}


def error_event(message: str) -> ErrorEvent:
    return {"type": "error", "message": message}


def done_event() -> DoneEvent:
    return {"type": "done"}


def encode_sse_event(event: SSEEvent) -> str:
    """Serialize typed events to the existing SSE wire format."""
    if event["type"] == "done":
        return "data: [DONE]\n\n"
    return f"data: {json.dumps(event)}\n\n"
