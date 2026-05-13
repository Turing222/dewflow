from types import SimpleNamespace
from typing import Any, cast

from backend.application.chat.history_projection import history_to_conversation_messages
from backend.application.chat.web_stream_workflow import ChatWorkflow


def test_stream_workflow_constructs_without_ai_dependencies():
    workflow = ChatWorkflow(
        uow=cast(Any, SimpleNamespace()),
        dispatcher=cast(Any, SimpleNamespace()),
        redis_client=cast(Any, SimpleNamespace()),
        permission_service=cast(Any, SimpleNamespace()),
    )

    assert workflow is not None


def test_history_projection_keeps_only_user_and_assistant_messages():
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
