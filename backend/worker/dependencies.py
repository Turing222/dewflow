"""Worker-only dependency assembly.

职责：为 TaskIQ worker 进程缓存重量级依赖，并装配 workflow 所需服务。
边界：Web/FastAPI 依赖仍由 backend.api.deps 提供；本模块只服务 worker。
"""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.ai.providers.embedding.rag_embedding import RAGEmbedderFactory
from backend.ai.providers.llm.factory import LLMProviderFactory
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.config.settings import settings
from backend.contracts.interfaces import (
    AbstractLLMService,
    AbstractRAGEmbedder,
    AbstractRAGService,
)
from backend.infra.database import create_db_assets
from backend.services.object_storage import ObjectStorage, create_object_storage
from backend.services.rag_planning_service import RAGPlanningService
from backend.services.rag_service import RAGService
from backend.services.unit_of_work import SQLAlchemyUnitOfWork
from backend.services.vector_index_service import VectorIndexService

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None
_llm_service: AbstractLLMService | None = None
_embedder: AbstractRAGEmbedder | None = None
_rag_service: AbstractRAGService | None = None
_rag_planning_service: RAGPlanningService | None = None
_object_storage: ObjectStorage | None = None


def get_worker_session_factory() -> async_sessionmaker:
    """Return the cached worker SQLAlchemy session factory."""
    global _engine, _session_factory
    if _session_factory is None:
        _engine, _session_factory = create_db_assets()
    return _session_factory


def get_worker_llm_service() -> AbstractLLMService:
    """Return the cached worker LLM service."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMProviderFactory.create()
    return _llm_service


def get_worker_embedder() -> AbstractRAGEmbedder:
    """Return the cached worker RAG embedder."""
    global _embedder
    if _embedder is None:
        profile = get_llm_model_config().resolve_embedding_profile(
            ai_settings.RAG_EMBED_PROVIDER
        )
        _embedder = RAGEmbedderFactory.create(
            provider=profile.provider,
            model_name=profile.model,
            base_url=profile.resolve_base_url(),
            api_key=profile.resolve_api_key(),
            dimensions=profile.dimensions,
        )
    return _embedder


def get_worker_rag_service(
    llm_service: AbstractLLMService | None = None,
) -> AbstractRAGService:
    """Return the cached worker-side RAG service for generation context retrieval."""
    global _rag_service
    if _rag_service is None:
        _llm = llm_service or get_worker_llm_service()
        uow = SQLAlchemyUnitOfWork(get_worker_session_factory())
        embedder = get_worker_embedder()
        vector_index_service = VectorIndexService(
            uow=uow,
            embedder=embedder,
            embed_batch_size=ai_settings.RAG_EMBED_BATCH_SIZE,
        )
        _rag_service = RAGService(
            uow=uow,
            embedder=embedder,
            vector_index_service=vector_index_service,
            top_k=ai_settings.RAG_TOP_K,
            llm_service=_llm,
            rerank_candidate_count=ai_settings.RAG_RERANK_CANDIDATE_COUNT,
            rerank_top_k=ai_settings.RAG_RERANK_TOP_K,
        )
    return _rag_service


def get_worker_rag_planning_service() -> RAGPlanningService:
    """Return the cached worker-side RAG planning service."""
    global _rag_planning_service
    if _rag_planning_service is None:
        _rag_planning_service = RAGPlanningService(
            provider=ai_settings.RAG_PLANNER_PROVIDER
        )
    return _rag_planning_service


def get_worker_object_storage() -> ObjectStorage:
    """Return the cached worker object storage adapter."""
    global _object_storage
    if _object_storage is None:
        _object_storage = create_object_storage(settings)
    return _object_storage
