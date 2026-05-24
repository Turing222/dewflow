"""Rerank provider factory unit tests.

职责：验证 RerankProviderFactory.create 分支逻辑；边界：monkeypatch 配置与 LLM model config；副作用：无。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ai.providers.rerank.bifrost_rerank import BifrostRerankService
from backend.ai.providers.rerank.factory import RerankProviderFactory


def _make_mock_config(
    base_url: str | None = "http://bifrost:8080/v1",
    api_key: str | None = "sk-test",
) -> object:
    profile = SimpleNamespace(
        resolve_base_url=lambda: base_url,
        resolve_api_key=lambda: api_key,
    )
    return SimpleNamespace(resolve_profile=lambda _name: profile)


def test_create_returns_none_when_provider_is_none_and_settings_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_PROVIDER", None
    )
    assert RerankProviderFactory.create(provider=None) is None


def test_create_returns_none_when_provider_is_empty_string() -> None:
    assert RerankProviderFactory.create(provider="") is None


def test_create_returns_none_when_provider_is_whitespace() -> None:
    assert RerankProviderFactory.create(provider="  ") is None


def test_create_constructs_bifrost_service_for_bifrost_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )

    result = RerankProviderFactory.create(provider="bifrost")

    assert isinstance(result, BifrostRerankService)
    assert result.base_url == "http://bifrost:8080/v1"
    assert result.api_key == "sk-test"
    assert result.model_name == "qwen3-rerank"


def test_create_accepts_llm_gateway_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )

    result = RerankProviderFactory.create(provider="llm-gateway")
    assert isinstance(result, BifrostRerankService)


def test_create_accepts_ai_gateway_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(),
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_MODEL",
        "qwen3-rerank",
    )
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.ai_settings.RAG_RERANK_TIMEOUT_SECONDS",
        15,
    )

    result = RerankProviderFactory.create(provider="ai-gateway")
    assert isinstance(result, BifrostRerankService)


def test_create_raises_value_error_for_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported RAG rerank provider"):
        RerankProviderFactory.create(provider="unknown-provider")


def test_create_raises_value_error_for_incomplete_bifrost_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.ai.providers.rerank.factory.get_llm_model_config",
        lambda: _make_mock_config(base_url=None),
    )

    with pytest.raises(ValueError, match="配置不完整"):
        RerankProviderFactory.create(provider="bifrost")
