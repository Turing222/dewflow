import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.application.chat.web_nonstream_workflow import ChatNonStreamWorkflow
from backend.models.orm.chat import MessageStatus
from backend.models.schemas.chat.commands import ChatQueryCommand
from backend.models.schemas.chat.context_state import ContextState
from backend.models.schemas.chat.payloads import GenerationResult

pytestmark = pytest.mark.asyncio


def _build_workflow(uow=None, dispatcher=None, redis_client=None):
    return ChatNonStreamWorkflow(
        uow=uow or MagicMock(),
        dispatcher=dispatcher or AsyncMock(),
        redis_client=redis_client or AsyncMock(),
        permission_service=MagicMock(),
    )


async def test_idempotency():
    uow = MagicMock()

    mock_redis = AsyncMock()
    mock_redis.set.side_effect = [True, False]
    mock_redis.get.return_value = "processing:test-uuid"

    workflow = _build_workflow(uow=uow, redis_client=mock_redis)

    user_id = uuid.uuid4()
    client_req_id = "test-req-123"

    mock_user = MagicMock(used_tokens=0, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get = AsyncMock(return_value=mock_user)
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.__aenter__.return_value = uow

    first_call_error: Exception | None = None
    try:
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )
    except Exception as exc:
        first_call_error = exc

    assert "正在加速计算中" not in str(first_call_error)
    mock_redis.set.assert_awaited_once()
    lock_key, lock_token = mock_redis.set.await_args.args
    assert lock_key == f"idempotency:chat:{user_id}:{client_req_id}"
    assert lock_token.startswith("processing:")
    assert mock_redis.set.await_args.kwargs == {"nx": True, "ex": 300}

    with pytest.raises(Exception, match="正在加速计算中"):
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )


async def test_token_quota():
    uow = MagicMock()
    workflow = _build_workflow(uow=uow)
    user_id = uuid.uuid4()

    mock_user = MagicMock(used_tokens=1000, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get = AsyncMock(return_value=mock_user)
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.__aenter__.return_value = uow

    with pytest.raises(Exception, match="Token 余额不足"):
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
            )
        )


async def test_idempotency_replay_with_non_success_message_does_not_prepare_request():
    uow = MagicMock()
    user_id = uuid.uuid4()
    client_req_id = "test-req-failed"
    mock_redis = AsyncMock()
    mock_redis.set.return_value = False
    mock_redis.get.return_value = "completed:test-uuid"
    workflow = _build_workflow(uow=uow, redis_client=mock_redis)

    failed_msg = MagicMock(status=MessageStatus.FAILED)
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_message_by_client_request_id = AsyncMock(
        return_value=failed_msg
    )
    uow.__aenter__.return_value = uow

    with (
        patch(
            "backend.application.chat.session_orchestrator.ChatSessionOrchestrator.prepare_request",
            AsyncMock(),
        ) as prepare_request,
        pytest.raises(Exception, match="刷新页面"),
    ):
        await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
                client_request_id=client_req_id,
            )
        )

    prepare_request.assert_not_awaited()


async def test_worker_dispatch_on_success():
    """Verify the web workflow dispatches to worker and returns response on success."""
    uow = MagicMock()
    user_id = uuid.uuid4()

    mock_worker_result = GenerationResult(
        success=True,
        content="Hello from worker",
        tokens_input=10,
        tokens_output=5,
        search_context=None,
        latency_ms=200,
    )
    mock_dispatcher = AsyncMock()
    mock_dispatcher.enqueue_nonstream = AsyncMock(return_value=mock_worker_result)
    workflow = _build_workflow(uow=uow, dispatcher=mock_dispatcher)

    mock_user = MagicMock(used_tokens=0, max_tokens=1000)
    uow.user_repo = AsyncMock()
    uow.user_repo.get_with_lock = AsyncMock(return_value=mock_user)
    uow.user_repo.try_increment_used_tokens_with_limit = AsyncMock(return_value=True)
    uow.knowledge_repo = AsyncMock()
    uow.knowledge_repo.get_kb_by_name_for_user = AsyncMock(return_value=None)
    uow.chat_repo = AsyncMock()
    uow.chat_repo.get_context_state = AsyncMock(return_value=ContextState())
    uow.__aenter__.return_value = uow

    session = MagicMock(id=uuid.uuid4(), title="Test Session", kb_id=None)
    now = datetime.now(UTC)
    assistant_msg = MagicMock(
        id=uuid.uuid4(),
        session_id=session.id,
        created_at=now,
        updated_at=now,
    )

    with (
        patch(
            "backend.services.chat_service.SessionManager.ensure_session",
            AsyncMock(return_value=session),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_user_message",
            AsyncMock(),
        ),
        patch(
            "backend.services.chat_service.SessionManager.create_assistant_message",
            AsyncMock(return_value=assistant_msg),
        ),
        patch(
            "backend.services.chat_service.SessionManager.get_session_messages",
            AsyncMock(return_value=[]),
        ),
        patch(
            "backend.application.chat.session_orchestrator.history_to_conversation_messages",
            return_value=[],
        ),
    ):
        result = await workflow.handle_query(
            ChatQueryCommand(
                user_id=user_id,
                query_text="hello",
            )
        )

    assert result is not None
    assert result.session_id == session.id
    assert result.session_title == "Test Session"
    assert result.answer.content == "Hello from worker"
    mock_dispatcher.enqueue_nonstream.assert_awaited_once()
