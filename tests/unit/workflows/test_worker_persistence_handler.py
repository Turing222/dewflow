"""Worker persistence handler tests — token billing and failure persistence.

职责：验证 WorkerPersistenceHandler 的成功持久化（token 计费、幂等锁更新）和失败持久化
（Redis 锁清理、消息状态写入）；边界：不启动 HTTP stack 或真实 Redis；副作用：无。
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.models.orm.chat import MessageStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_persistence_uow() -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.user_repo = AsyncMock()
    uow.chat_repo = AsyncMock()
    uow.chat_repo.update_message_status = AsyncMock()
    return uow


@pytest.fixture
def fake_persistence_redis() -> AsyncMock:
    redis_client = AsyncMock()
    redis_client.init = AsyncMock()
    return redis_client


async def test_persist_success_token_limit_exceeded_writes_failed(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    assistant_message_id = uuid.uuid4()
    fake_persistence_uow.user_repo.try_increment_used_tokens_with_limit = AsyncMock(
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

    fake_persistence_uow.chat_repo.update_message_status.assert_awaited_once()
    call_kwargs = fake_persistence_uow.chat_repo.update_message_status.call_args.kwargs
    assert call_kwargs["status"] == MessageStatus.FAILED
    assert call_kwargs["content"] == "Token 余额不足，本次消耗未记录"
    assert call_kwargs["message_metadata"]["response_outcome"] == "failed"


async def test_persist_success_assistant_message_id_none_skips(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    await handler.persist_success(
        assistant_message_id=None,
        user_id=uuid.uuid4(),
        content="content",
        tokens_input=100,
        tokens_output=50,
        search_context=None,
        start_time=0.0,
    )

    fake_persistence_uow.user_repo.try_increment_used_tokens_with_limit.assert_not_awaited()
    fake_persistence_uow.chat_repo.update_message_status.assert_not_awaited()


async def test_persist_failure_redis_lock_cleanup_fails_still_writes_message(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    mock_redis_conn = AsyncMock()
    mock_redis_conn.delete = AsyncMock(side_effect=ConnectionError("Redis gone"))
    fake_persistence_redis.init = AsyncMock(return_value=mock_redis_conn)

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    await handler.persist_failure(
        assistant_message_id=uuid.uuid4(),
        error_content="something failed",
        idempotency_lock_key="somekey",
    )

    mock_redis_conn.delete.assert_awaited_once_with("somekey")
    fake_persistence_uow.chat_repo.update_message_status.assert_awaited_once()
    assert (
        fake_persistence_uow.chat_repo.update_message_status.call_args.kwargs["status"]
        == MessageStatus.FAILED
    )


async def test_persist_failure_update_throws_swallowed(
    fake_persistence_uow, fake_persistence_redis
) -> None:
    from backend.application.chat.worker_persistence_handler import (
        WorkerPersistenceHandler,
    )

    fake_persistence_uow.chat_repo.update_message_status = AsyncMock(
        side_effect=RuntimeError("DB error")
    )

    handler = WorkerPersistenceHandler(
        uow=fake_persistence_uow, redis_client=fake_persistence_redis
    )

    await handler.persist_failure(
        assistant_message_id=uuid.uuid4(),
        error_content="failed",
        idempotency_lock_key=None,
    )

    fake_persistence_uow.chat_repo.update_message_status.assert_awaited_once()
