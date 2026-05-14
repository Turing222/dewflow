"""Worker lifecycle hook tests — startup/shutdown dependency init and cleanup."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_shutdown_dependencies_cleans_up_redis_on_container_error(monkeypatch):
    from backend.infra import task_broker
    from backend.infra.redis import redis_client
    from backend.worker import dependencies as worker_deps

    # Ensure container exists so close_worker_container has something to clean up.
    worker_deps.get_worker_container()

    async def mock_close_that_raises():
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_deps, "close_worker_container", mock_close_that_raises)
    mock_redis_close = AsyncMock()
    monkeypatch.setattr(redis_client, "close", mock_redis_close)

    with pytest.raises(RuntimeError, match="boom"):
        await task_broker._shutdown_worker_dependencies(None)

    mock_redis_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_dependencies_creates_worker_container(monkeypatch):
    from backend.infra import task_broker
    from backend.worker import dependencies as worker_deps

    # Reset container state before test.
    worker_deps.set_worker_container(None)

    # Patch session factory creation to avoid DB connection attempt.
    async def mock_close():
        pass

    monkeypatch.setattr(worker_deps.WorkerContainer, "close", mock_close)
    monkeypatch.setattr(worker_deps.WorkerContainer, "get_session_factory", lambda self: None)

    await task_broker._startup_worker_dependencies(None)

    container = worker_deps.get_worker_container()
    assert container is not None
