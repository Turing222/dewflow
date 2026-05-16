"""Knowledge API unit tests.

职责：验证 endpoint 对上传 workflow 的参数传递和响应返回；边界：直接调用 endpoint 函数，不启动 FastAPI app 或真实存储；副作用：无。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from backend.api.v1.endpoint import knowledge_api
from backend.models.schemas.knowledge_schema import KnowledgeUploadResponse

pytestmark = pytest.mark.asyncio


async def test_upload_file_delegates_to_submit_workflow() -> None:
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)
    expected = KnowledgeUploadResponse(
        task_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        kb_id=kb_id,
        file_status="uploaded",
        task_status="pending",
    )
    upload_workflow = SimpleNamespace(submit=AsyncMock(return_value=expected))

    result = await knowledge_api.upload_file(
        kb_id=kb_id,
        file=upload_file,
        current_user=SimpleNamespace(id=user_id),
        upload_workflow=upload_workflow,
        audit_service=SimpleNamespace(),
    )

    assert result == expected
    upload_workflow.submit.assert_awaited_once_with(
        kb_id=kb_id,
        user_id=user_id,
        upload_file=upload_file,
    )


async def test_upload_file_to_default_kb_delegates_to_submit_workflow() -> None:
    user_id = uuid.uuid4()
    upload_file = MagicMock(spec=UploadFile)
    expected = KnowledgeUploadResponse(
        task_id=uuid.uuid4(),
        file_id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        file_status="uploaded",
        task_status="pending",
    )
    upload_workflow = SimpleNamespace(submit=AsyncMock(return_value=expected))

    result = await knowledge_api.upload_file_to_default_kb(
        file=upload_file,
        current_user=SimpleNamespace(id=user_id),
        upload_workflow=upload_workflow,
        audit_service=SimpleNamespace(),
    )

    assert result == expected
    upload_workflow.submit.assert_awaited_once_with(
        user_id=user_id,
        upload_file=upload_file,
    )
