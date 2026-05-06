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


def encode_chunk_event(content: str) -> str:
    return json.dumps({"type": "chunk", "content": content}, ensure_ascii=False)


def encode_error_event(message: str) -> str:
    return json.dumps({"type": "error", "message": message}, ensure_ascii=False)


def encode_done_event() -> str:
    return json.dumps({"type": "done"}, ensure_ascii=False)


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
        return {"type": "chunk", "content": str(data.get("content") or "")}
    if event_type == "error":
        return {"type": "error", "message": str(data.get("message") or "")}
    if event_type == "done":
        return {"type": "done"}
    return _decode_legacy_payload(payload)


def _decode_legacy_payload(payload: str) -> StreamEvent:
    if payload == "[DONE]":
        return {"type": "done"}
    if payload.startswith("[ERROR]"):
        return {"type": "error", "message": payload[7:]}
    return {"type": "chunk", "content": payload}
