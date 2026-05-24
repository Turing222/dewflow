"""Worker dependencies unit tests.

职责：验证 WorkerContainer 关闭清理和 wrapper 函数委托行为；边界：使用 DummyEngine/DummyContainer 替身，不连接真实基础设施；副作用：无。
"""

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.requires_taskiq


@pytest.fixture(autouse=True)
def reset_worker_container() -> None:
    from backend.worker import dependencies

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
        self.external_context_provider = object()
        self.object_storage = object()
        self.close = AsyncMock()

    def get_session_factory(self) -> object:
        return self.session_factory

    def get_llm_service(self) -> object:
        return self.llm_service

    def get_embedder(self) -> object:
        return self.embedder

    def get_rag_service(self, llm_service: object = None) -> object:  # type: ignore[override]
        return self.rag_service

    def get_rag_planning_service(self) -> object:
        return self.rag_planning_service

    def get_external_context_provider(self) -> object:
        return self.external_context_provider

    def get_object_storage(self) -> object:
        return self.object_storage


@pytest.mark.asyncio
async def test_worker_container_close_disposes_engine_and_clears_refs() -> None:
    from backend.worker.dependencies import WorkerContainer

    container = WorkerContainer()
    engine = DummyEngine()
    llm_service = AsyncMock()
    embedder = AsyncMock()
    external_context_provider = AsyncMock()
    container._engine = engine
    container._session_factory = object()
    container._llm_service = llm_service
    container._embedder = embedder
    container._rag_service = object()
    container._rag_planning_service = object()
    container._external_context_provider = external_context_provider
    container._object_storage = object()

    await container.close()

    engine.dispose.assert_awaited_once()
    llm_service.close.assert_awaited_once()
    embedder.close.assert_awaited_once()
    external_context_provider.close.assert_awaited_once()
    assert container._engine is None
    assert container._session_factory is None
    assert container._llm_service is None
    assert container._embedder is None
    assert container._rag_service is None
    assert container._rag_planning_service is None
    assert container._external_context_provider is None
    assert container._object_storage is None


def test_wrapper_functions_delegate_to_container_return_services() -> None:
    from backend.worker import dependencies

    container = DummyContainer()
    dependencies.set_worker_container(container)

    assert dependencies.get_worker_session_factory() is container.session_factory
    assert dependencies.get_worker_llm_service() is container.llm_service
    assert dependencies.get_worker_embedder() is container.embedder
    assert dependencies.get_worker_rag_service() is container.rag_service
    assert (
        dependencies.get_worker_rag_planning_service() is container.rag_planning_service
    )
    assert (
        dependencies.get_worker_external_context_provider()
        is container.external_context_provider
    )
    assert dependencies.get_worker_object_storage() is container.object_storage


@pytest.mark.asyncio
async def test_get_external_context_provider_lazy_init(monkeypatch) -> None:
    from backend.worker.dependencies import WorkerContainer

    fake_provider = AsyncMock()
    monkeypatch.setattr(
        "backend.worker.dependencies.create_external_context_provider",
        lambda: fake_provider,
    )

    container = WorkerContainer()
    assert container._external_context_provider is None

    result1 = container.get_external_context_provider()
    assert result1 is fake_provider
    assert container._external_context_provider is fake_provider

    result2 = container.get_external_context_provider()
    assert result2 is fake_provider
