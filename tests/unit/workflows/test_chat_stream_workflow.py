"""Chat stream workflow construction and history projection tests.

职责：验证 ChatWorkflow 轻量构造和 history_to_conversation_messages 的消息过滤；
边界：不启动 HTTP stack、不依赖 AI 服务；副作用：无。
"""

from types import SimpleNamespace
from typing import Any, cast

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.application.chat.web_stream_workflow import ChatWorkflow


def test_stream_workflow_constructs_without_ai_dependencies() -> None:
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=cast(Any, SimpleNamespace()),
        redis_client=cast(Any, SimpleNamespace()),
        permission_service=cast(Any, SimpleNamespace()),
    )

    assert workflow is not None


def test_history_projection_keeps_only_user_and_assistant_messages() -> None:
    messages = [
        SimpleNamespace(role="system", content="ignore"),
        SimpleNamespace(role="user", content="hello"),
        {"role": "assistant", "content": "hi"},
        {"role": "assistant", "content": ""},
    ]

    assert history_to_conversation_messages(messages) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
