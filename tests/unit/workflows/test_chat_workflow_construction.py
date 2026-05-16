"""Chat workflow construction test — verifies lightweight wiring with test doubles.

职责：验证聊天 workflow 可用测试替身完成轻量构造；边界：不启动 HTTP stack、worker 或真实外部依赖；副作用：无。
"""

from unittest.mock import AsyncMock, MagicMock

from backend.application.chat.web_stream_workflow import ChatWorkflow


def test_minimal_workflow_construction() -> None:
    uow = MagicMock()
    dispatcher = AsyncMock()
    redis_client = AsyncMock()
    permission_service = MagicMock()
    workflow = ChatWorkflow(uow, dispatcher, redis_client, permission_service)

    assert workflow is not None
