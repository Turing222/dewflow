"""HTTP Server-Sent Events for chat streaming.

职责：序列化 typed event 为 HTTP SSE wire format。
边界：事件类型定义已移至 application.chat.stream_events；
      本模块仅保留 encode_sse_event 和向后兼容的重导出。
"""

import json

from backend.application.chat.stream_events import (  # noqa: F401 — backward-compat re-exports
    ChunkEvent,
    DoneEvent,
    ErrorEvent,
    MetaEvent,
    SSEEvent,
    chunk_event,
    done_event,
    error_event,
    meta_event,
)


def encode_sse_event(event: SSEEvent) -> str:
    """Serialize typed events to the existing SSE wire format."""
    if event["type"] == "done":
        return "data: [DONE]\n\n"
    return f"data: {json.dumps(event)}\n\n"
