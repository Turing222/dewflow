"""Chat API unit tests.

职责：验证 chat endpoint 的 stream event 序列化和审计记录；边界：直接调用 endpoint 函数，不启动 HTTP stack 或真实 worker；副作用：无。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from backend.api.v1.endpoint import chat_api
from backend.services.audit_service import AuditService

pytestmark = pytest.mark.asyncio


class CapturingSession:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    async def __aenter__(self) -> CapturingSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def add(self, event: object) -> None:
        self.events.append(event)

    async def commit(self) -> None:
        return None


class CapturingSessionFactory:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self) -> CapturingSession:
        return CapturingSession(self.events)


class TypedStreamWorkflow:
    async def handle_query_stream(self, command: Any) -> AsyncIterator[dict[str, str]]:
        message_id = uuid.uuid4()
        yield {
            "type": "meta",
            "session_id": str(command.session_id or uuid.uuid4()),
            "session_title": "demo",
            "message_id": str(message_id),
        }
        yield {"type": "chunk", "content": "hello"}
        yield {"type": "done"}


async def test_query_stream_serializes_typed_events_and_audits_meta_resource() -> None:
    session_factory = CapturingSessionFactory()
    audit_service = AuditService(
        uow=SimpleNamespace(),
        session_factory=session_factory,
    )
    request = SimpleNamespace(
        query="hello",
        session_id=None,
        kb_id=None,
        client_request_id="client-1",
        extra_body=None,
    )

    response = await chat_api.query_stream(
        request=request,
        current_user=SimpleNamespace(id=uuid.uuid4()),
        workflow=TypedStreamWorkflow(),
        _=None,
        audit_service=audit_service,
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks[0].startswith('data: {"type": "meta"')
    assert chunks[1] == 'data: {"type": "chunk", "content": "hello"}\n\n'
    assert chunks[2] == "data: [DONE]\n\n"
    assert len(session_factory.events) == 1
    assert session_factory.events[0].resource_type == "chat_session"
    assert session_factory.events[0].resource_id is not None
