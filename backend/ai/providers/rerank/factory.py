"""Rerank provider factory."""

from backend.ai.providers.rerank.bifrost_rerank import BifrostRerankService
from backend.config.ai_settings import ai_settings
from backend.config.llm import get_llm_model_config
from backend.contracts.interfaces import AbstractRerankService


class RerankProviderFactory:
    """按配置构建 rerank 服务实例。"""

    @staticmethod
    def create(provider: str | None = None) -> AbstractRerankService | None:
        normalized = (provider or ai_settings.RAG_RERANK_PROVIDER or "").strip().lower()
        if not normalized:
            return None

        if normalized in {"bifrost", "llm-gateway", "ai-gateway"}:
            profile = get_llm_model_config().resolve_profile("bifrost")
            base_url = profile.resolve_base_url()
            api_key = profile.resolve_api_key()
            if not base_url or not api_key:
                raise ValueError("Bifrost rerank 配置不完整，请检查 BASE_URL/API_KEY")
            return BifrostRerankService(
                base_url=base_url,
                api_key=api_key,
                model_name=ai_settings.RAG_RERANK_MODEL,
                timeout_seconds=ai_settings.RAG_RERANK_TIMEOUT_SECONDS,
            )

        raise ValueError(f"Unsupported RAG rerank provider: {provider}")
