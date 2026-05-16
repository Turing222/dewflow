"""Audit API unit tests.

职责：验证 audit endpoint 的权限检查、superuser 分支和全局审计限制；边界：直接调用 endpoint 函数并使用 fake UoW；副作用：无。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.v1.endpoint import audit_api
from backend.core.exceptions import AppException
from backend.services.permission_service import Permission

pytestmark = pytest.mark.asyncio


class DummyUoW:
    def __init__(self) -> None:
        self.audit_repo = SimpleNamespace(
            count_events=AsyncMock(return_value=0),
            list_events=AsyncMock(return_value=[]),
        )

    def read_context(self) -> DummyUoW:
        return self

    async def __aenter__(self) -> DummyUoW:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def make_user(**overrides: object) -> SimpleNamespace:
    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "username": "tester",
        "email": "tester@example.com",
        "is_active": True,
        "is_superuser": False,
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_permission_service() -> SimpleNamespace:
    return SimpleNamespace(
        policy=SimpleNamespace(superuser_bypass=True),
        require_permission=AsyncMock(),
    )


async def test_workspace_audit_events_require_audit_read_permission() -> None:
    workspace_id = uuid.uuid4()
    current_user = make_user()
    permission_service = make_permission_service()

    result = await audit_api.list_audit_events(
        current_user=current_user,
        uow=DummyUoW(),
        permission_service=permission_service,
        workspace_id=workspace_id,
        action=None,
        request_id=None,
    )

    assert result.total == 0
    permission_service.require_permission.assert_awaited_once_with(
        user=current_user,
        workspace_id=workspace_id,
        permission=Permission.AUDIT_READ,
    )


async def test_non_superuser_cannot_read_global_audit_events() -> None:
    permission_service = make_permission_service()

    with pytest.raises(AppException) as exc_info:
        await audit_api.list_audit_events(
            current_user=make_user(),
            uow=DummyUoW(),
            permission_service=permission_service,
            workspace_id=None,
            action=None,
            request_id=None,
        )

    assert exc_info.value.status_code == 403
    permission_service.require_permission.assert_not_awaited()


async def test_superuser_can_read_global_audit_events_without_role_check() -> None:
    permission_service = make_permission_service()

    result = await audit_api.list_audit_events(
        current_user=make_user(is_superuser=True),
        uow=DummyUoW(),
        permission_service=permission_service,
        workspace_id=None,
        action=None,
        request_id=None,
    )

    assert result.total == 0
    permission_service.require_permission.assert_not_awaited()
