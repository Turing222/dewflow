"""Worker-only dependency assembly.

职责：为 TaskIQ worker 进程缓存重量级依赖，并装配 workflow 所需服务。
边界：Web/FastAPI 依赖仍由 backend.api.deps 提供；本模块只服务 worker。
"""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import AbstractLLMService, AbstractRAGEmbedder
from backend.infra.database import create_db_assets
from backend.services.object_storage import ObjectStorage, create_object_storage

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_embedder: AbstractRAGEmbedder | None = None
_object_storage: ObjectStorage | None = None


def get_worker_session_factory() -> async_sessionmaker:
    """Return the cached worker SQLAlchemy session factory."""
    global _engine, _session_factory
    if _session_factory is None:
        _engine, _session_factory = create_db_assets()
    return _session_factory


def get_worker_llm_service() -> AbstractLLMService:
    """Create an LLM service for worker generation tasks."""
    return LLMProviderFactory.create()


def get_worker_embedder() -> AbstractRAGEmbedder:
    """Return the cached worker RAG embedder."""
    global _embedder
    if _embedder is None:
        profile = get_llm_model_config().resolve_embedding_profile(
            settings.RAG_EMBED_PROVIDER
        )
        _embedder = RAGEmbedderFactory.create(
            provider=profile.provider,
            model_name=profile.model,
            base_url=profile.resolve_base_url(),
            api_key=profile.resolve_api_key(),
            dimensions=profile.dimensions,
        )
    return _embedder


def get_worker_object_storage() -> ObjectStorage:
    """Return the cached worker object storage adapter."""
    global _object_storage
    if _object_storage is None:
        _object_storage = create_object_storage(settings)
    return _object_storage

