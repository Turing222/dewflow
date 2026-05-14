"""Unit tests for WorkerPersistenceHandler — token billing and failure persistence."""

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.models.orm.chat import MessageStatus


@pytest.fixture
def mock_uow():
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.user_repo = AsyncMock()
    uow.chat_repo = AsyncMock()
    uow.chat_repo.update_message_status = AsyncMock()
    return uow


@pytest.fixture
def mock_redis_client():
    redis_client = AsyncMock()
    redis_client.init = AsyncMock()
    return redis_client


@pytest.mark.asyncio
async def test_persist_success_token_limit_exceeded_writes_failed(
    mock_uow, mock_redis_client
):
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(uow=mock_uow, redis_client=mock_redis_client)

    assistant_message_id = uuid.uuid4()
    mock_uow.user_repo.try_increment_used_tokens_with_limit = AsyncMock(
        return_value=False
    )

    await handler.persist_success(
        assistant_message_id=assistant_message_id,
        user_id=uuid.uuid4(),
        content="some content",
        tokens_input=100,
        tokens_output=50,
        search_context=None,
        start_time=0.0,
    )

    mock_uow.chat_repo.update_message_status.assert_awaited_once()
    call_kwargs = mock_uow.chat_repo.update_message_status.call_args.kwargs
    assert call_kwargs["status"] == MessageStatus.FAILED
    assert call_kwargs["content"] == "Token 余额不足，本次消耗未记录"
    assert call_kwargs["message_metadata"]["response_outcome"] == "failed"


@pytest.mark.asyncio
async def test_persist_success_assistant_message_id_none_skips(
    mock_uow, mock_redis_client
):
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(uow=mock_uow, redis_client=mock_redis_client)

    await handler.persist_success(
        assistant_message_id=None,
        user_id=uuid.uuid4(),
        content="content",
        tokens_input=100,
        tokens_output=50,
        search_context=None,
        start_time=0.0,
    )

    mock_uow.user_repo.try_increment_used_tokens_with_limit.assert_not_awaited()
    mock_uow.chat_repo.update_message_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_failure_redis_lock_cleanup_fails_still_writes_message(
    mock_uow, mock_redis_client
):
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    mock_redis_conn = AsyncMock()
    mock_redis_conn.delete = AsyncMock(side_effect=ConnectionError("Redis gone"))
    mock_redis_client.init = AsyncMock(return_value=mock_redis_conn)

    handler = WorkerPersistenceHandler(uow=mock_uow, redis_client=mock_redis_client)

    await handler.persist_failure(
        assistant_message_id=uuid.uuid4(),
        error_content="something failed",
        idempotency_lock_key="somekey",
    )

    mock_redis_conn.delete.assert_awaited_once_with("somekey")
    mock_uow.chat_repo.update_message_status.assert_awaited_once()
    assert (
        mock_uow.chat_repo.update_message_status.call_args.kwargs["status"]
        == MessageStatus.FAILED
    )


@pytest.mark.asyncio
async def test_persist_failure_update_throws_swallowed(
    mock_uow, mock_redis_client
):
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    mock_uow.chat_repo.update_message_status = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    handler = WorkerPersistenceHandler(uow=mock_uow, redis_client=mock_redis_client)

    # Should not raise — exception is swallowed internally.
    await handler.persist_failure(
        assistant_message_id=uuid.uuid4(),
        error_content="failed",
        idempotency_lock_key=None,
    )

    mock_uow.chat_repo.update_message_status.assert_awaited_once()
