"""Internal stream events for Worker-to-Web Redis channels.

职责：统一 worker 发布到 Redis 的流式事件格式。
边界：这是内部通道协议；HTTP SSE 对外格式仍由 Web workflow 决定。
"""

import json
from typing import Literal, TypedDict

StreamEventType = Literal["chunk", "error", "done"]


class StreamEvent(TypedDict, total=False):
    """Normalized internal stream event."""

    type: StreamEventType
    content: str
    message: str


def stream_chunk_event(content: str) -> StreamEvent:
    return {"type": "chunk", "content": content}


def stream_error_event(message: str) -> StreamEvent:
    return {"type": "error", "message": message}


def stream_done_event() -> StreamEvent:
    return {"type": "done"}


def encode_chunk_event(content: str) -> str:
    return json.dumps(stream_chunk_event(content), ensure_ascii=False)


def encode_error_event(message: str) -> str:
    return json.dumps(stream_error_event(message), ensure_ascii=False)


def encode_done_event() -> str:
    return json.dumps(stream_done_event(), ensure_ascii=False)


def decode_stream_event(payload: str) -> StreamEvent:
    """Decode structured events, accepting legacy raw payloads during rollout."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return _decode_legacy_payload(payload)

    if not isinstance(data, dict):
        return _decode_legacy_payload(payload)

    event_type = data.get("type")
    if event_type == "chunk":
        return stream_chunk_event(str(data.get("content") or ""))
    if event_type == "error":
        return stream_error_event(str(data.get("message") or ""))
    if event_type == "done":
        return stream_done_event()
    return _decode_legacy_payload(payload)


def _decode_legacy_payload(payload: str) -> StreamEvent:
    if payload == "[DONE]":
        return stream_done_event()
    if payload.startswith("[ERROR]"):
        return stream_error_event(payload[7:])
    return stream_chunk_event(payload)
