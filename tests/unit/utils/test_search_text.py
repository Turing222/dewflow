"""Search text utility unit tests.

职责：验证 search_text 模块的 token 提取、去重、限流和查询归一化行为；边界：纯函数调用，不依赖外部服务；副作用：无。
"""

from backend.utils.search_text import (
    build_search_text,
    deduplicate,
    limit_tokens,
    normalize_query,
)


def test_deduplicate_preserves_first_seen_order() -> None:
    result = deduplicate(["数据库", "连接数", "数据库", "错误"])

    assert result == ["数据库", "连接数", "错误"]


def test_limit_tokens_caps_tokens_without_reordering() -> None:
    result = limit_tokens(["a", "b", "c"], max_n=2)

    assert result == ["a", "b"]


def test_build_search_text_keeps_content_and_repeats_keywords_in_output() -> None:
    content = "PostgreSQL 数据库连接数错误，请检查 max_connections 和 PG_POOL_SIZE。"

    search_text = build_search_text(content)

    assert search_text.splitlines()[0] == content
    assert search_text.count("max_connections") == 3  # 1 original + 2 repeat
    assert search_text.count("PG_POOL_SIZE") == 3
    assert "数据库" in search_text


def test_build_search_text_returns_empty_string_on_blank_content() -> None:
    assert build_search_text("   ") == ""


def test_normalize_query_extracts_tokens_without_keyword_boost() -> None:
    query = "数据库 max_connections"

    normalized_query = normalize_query(query)

    assert normalized_query.splitlines()[0] == query
    assert normalized_query.count("max_connections") == 2
    assert "数据库" in normalized_query
