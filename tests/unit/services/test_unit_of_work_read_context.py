from unittest.mock import AsyncMock

import pytest

from backend.services import unit_of_work as uow_module
from backend.services.unit_of_work import SQLAlchemyUnitOfWork


class DummySession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()


class DummyRepository:
    def __init__(self, session: DummySession) -> None:
        self.session = session


@pytest.fixture(autouse=True)
def patch_repositories(monkeypatch) -> None:
    for name in (
        "AccessRepository",
        "AuditRepository",
        "ChatRepository",
        "KnowledgeRepository",
        "TaskRepository",
        "UserRepository",
    ):
        monkeypatch.setattr(uow_module, name, DummyRepository)


@pytest.mark.asyncio
async def test_read_context_closes_without_commit() -> None:
    session = DummySession()
    uow = SQLAlchemyUnitOfWork(lambda: session)

    async with uow.read_context():
        assert uow.session is session
        assert uow.chat_repo.session is session

    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_read_context_rolls_back_on_exception() -> None:
    session = DummySession()
    uow = SQLAlchemyUnitOfWork(lambda: session)

    with pytest.raises(ValueError, match="boom"):
        async with uow.read_context():
            raise ValueError("boom")

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
