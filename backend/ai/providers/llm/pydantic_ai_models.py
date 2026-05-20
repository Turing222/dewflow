"""Pydantic AI model construction helpers.

职责：把 Dewflow 的 LLM profile 转换为 Pydantic AI model 实例。
边界：本模块只处理 provider SDK 适配，不执行 Agent 调用或业务编排。
失败处理：缺少依赖、API key 或不支持的 provider 会转换为统一业务错误。
"""

from typing import Any

from backend.config.llm import LLMProfile
from backend.core.exceptions import app_service_error

GOOGLE_PROVIDERS = {"google", "gemini", "pydantic-ai", "pydantic_ai"}
OPENAI_COMPATIBLE_PROVIDERS = {"openai", "openai-compatible", "deepseek"}
SUPPORTED_PROVIDERS = GOOGLE_PROVIDERS | OPENAI_COMPATIBLE_PROVIDERS


def create_pydantic_ai_model(
    *,
    profile: LLMProfile,
    api_key: str | None,
    max_retries: int | None = None,
) -> Any:
    """Create a Pydantic AI model from a runtime LLM profile."""
    normalized_provider = profile.provider.strip().lower()
    resolved_api_key = api_key or profile.resolve_api_key()
    if not resolved_api_key:
        raise app_service_error(
            "LLM API Key 未配置",
            code="LLM_API_KEY_MISSING",
            details={"provider": profile.provider, "profile": profile.name},
        )

    if normalized_provider in GOOGLE_PROVIDERS:
        return _create_google_model(profile=profile, api_key=resolved_api_key)

    if normalized_provider in OPENAI_COMPATIBLE_PROVIDERS:
        return _create_openai_compatible_model(
            profile=profile,
            api_key=resolved_api_key,
            max_retries=max_retries,
        )

    raise app_service_error(
        "不支持的 LLM Provider",
        code="LLM_PROVIDER_UNSUPPORTED",
        details={"provider": profile.provider, "profile": profile.name},
    )


def _create_google_model(*, profile: LLMProfile, api_key: str) -> Any:
    try:
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider
    except ImportError as exc:
        raise app_service_error(
            "Pydantic AI Google provider 未安装",
            code="PYDANTIC_AI_PROVIDER_MISSING",
            details={"install": 'uv add "pydantic-ai-slim[google]"'},
        ) from exc

    provider = GoogleProvider(api_key=api_key, base_url=profile.resolve_base_url())
    return GoogleModel(profile.model, provider=provider)


def _create_openai_compatible_model(
    *,
    profile: LLMProfile,
    api_key: str,
    max_retries: int | None,
) -> Any:
    try:
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
    except ImportError as exc:
        raise app_service_error(
            "Pydantic AI OpenAI provider 未安装",
            code="PYDANTIC_AI_PROVIDER_MISSING",
            details={"install": 'uv add "pydantic-ai-slim[openai]"'},
        ) from exc

    base_url = profile.resolve_base_url()
    if max_retries is None:
        provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    else:
        client_kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": max_retries}
        if base_url:
            client_kwargs["base_url"] = base_url
        provider = OpenAIProvider(openai_client=AsyncOpenAI(**client_kwargs))
    return OpenAIChatModel(profile.model, provider=provider)
