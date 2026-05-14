from unittest.mock import AsyncMock

import pytest

from backend.worker import dependencies
from backend.worker.dependencies import WorkerContainer


@pytest.fixture(autouse=True)
def reset_worker_container():
    dependencies.set_worker_container(None)
    yield
    dependencies.set_worker_container(None)


class DummyEngine:
    def __init__(self) -> None:
        self.dispose = AsyncMock()


class DummyContainer:
    def __init__(self) -> None:
        self.session_factory = object()
        self.llm_service = object()
        self.embedder = object()
        self.rag_service = object()
        self.rag_planning_service = object()
        self.object_storage = object()
        self.close = AsyncMock()

    def get_session_factory(self):
        return self.session_factory

    def get_llm_service(self):
        return self.llm_service

    def get_embedder(self):
        return self.embedder

    def get_rag_service(self, llm_service=None):
        return self.rag_service

    def get_rag_planning_service(self):
        return self.rag_planning_service

    def get_object_storage(self):
        return self.object_storage


@pytest.mark.asyncio
async def test_worker_container_close_disposes_engine() -> None:
    container = WorkerContainer()
    engine = DummyEngine()
    llm_service = AsyncMock()
    embedder = AsyncMock()
    container._engine = engine
    container._session_factory = object()
    container._llm_service = llm_service
    container._embedder = embedder
    container._rag_service = object()
    container._rag_planning_service = object()
    container._object_storage = object()

    await container.close()

    engine.dispose.assert_awaited_once()
    llm_service.close.assert_awaited_once()
    embedder.close.assert_awaited_once()
    assert container._engine is None
    assert container._session_factory is None
    assert container._llm_service is None
    assert container._embedder is None
    assert container._rag_service is None
    assert container._rag_planning_service is None
    assert container._object_storage is None


def test_worker_wrapper_functions_delegate_to_container() -> None:
    container = DummyContainer()
    dependencies.set_worker_container(container)

    assert dependencies.get_worker_session_factory() is container.session_factory
    assert dependencies.get_worker_llm_service() is container.llm_service
    assert dependencies.get_worker_embedder() is container.embedder
    assert dependencies.get_worker_rag_service() is container.rag_service
    assert (
        dependencies.get_worker_rag_planning_service()
        is container.rag_planning_service
    )
    assert dependencies.get_worker_object_storage() is container.object_storage
