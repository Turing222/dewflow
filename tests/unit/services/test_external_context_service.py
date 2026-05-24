"""External context provider unit tests.

职责：验证外部上下文 provider 的结果标准化与配置降级；边界：不连接真实 Tavily API。
"""

from backend.services.external_context_service import (
    TavilyExternalContextProvider,
    create_external_context_provider,
)


def test_tavily_parse_response_normalizes_chunks() -> None:
    provider = TavilyExternalContextProvider(api_key="key")

    chunks = provider._parse_response(
        {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com",
                    "content": "Fresh context",
                    "score": 0.8,
                }
            ]
        },
        top_k=3,
    )

    assert len(chunks) == 1
    rag_chunk = chunks[0].to_rag_chunk(chunk_index=0)
    assert rag_chunk["source_type"] == "web"
    assert rag_chunk["provider"] == "tavily"
    assert rag_chunk["url"] == "https://example.com"
    assert rag_chunk["evidence_score"] == 0.8


def test_create_external_context_provider_returns_none_when_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.external_context_service.ai_settings.EXTERNAL_CONTEXT_ENABLED",
        False,
    )

    assert create_external_context_provider() is None
