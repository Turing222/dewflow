"""Search text normalization helpers.

职责：为全文检索生成受控 search_text，并保持查询与入库侧 token 规则一致。
边界：本模块不访问数据库、不参与向量化、不读取文件元信息。
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

import jieba

from backend.config.ai_settings import ai_settings

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KEYWORD_RE = re.compile(
    r"\b(?:"
    r"[A-Z][A-Z0-9_]{2,}"
    r"|[A-Za-z0-9]+_[A-Za-z0-9_]+"
    r"|[A-Za-z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*"
    r"|[A-Za-z]+(?:\.[A-Za-z0-9_]+)+"
    r"|[A-Za-z0-9]+-[A-Za-z0-9-]+"
    r")\b"
)
_PUNCTUATION = set(string.punctuation) | set("，。！？；：、（）【】《》“”‘’…—·")


def build_search_text(content: str) -> str:
    normalized_content = content.strip()
    if not normalized_content:
        return ""

    zh_tokens = limit_tokens(
        deduplicate(extract_zh_tokens(normalized_content)),
        max_n=ai_settings.SEARCH_TEXT_DEFAULT_TOKEN_LIMIT,
    )
    keyword_tokens = limit_tokens(
        deduplicate(extract_keyword_tokens(normalized_content)),
        max_n=ai_settings.SEARCH_TEXT_KEYWORD_TOKEN_LIMIT,
    )
    parts = [normalized_content, " ".join(zh_tokens)]
    parts.extend(
        " ".join(keyword_tokens)
        for _ in range(ai_settings.SEARCH_TEXT_KEYWORD_REPEAT)
    )
    return "\n".join(part for part in parts if part)


def build_search_texts(contents: Iterable[str]) -> list[str]:
    return [build_search_text(content) for content in contents]


def normalize_query(query_text: str) -> str:
    normalized_query = query_text.strip()
    if not normalized_query:
        return ""

    zh_tokens = limit_tokens(
        deduplicate(extract_zh_tokens(normalized_query)),
        max_n=ai_settings.SEARCH_TEXT_DEFAULT_TOKEN_LIMIT,
    )
    keyword_tokens = limit_tokens(
        deduplicate(extract_keyword_tokens(normalized_query)),
        max_n=ai_settings.SEARCH_TEXT_KEYWORD_TOKEN_LIMIT,
    )
    parts = [normalized_query, " ".join(zh_tokens), " ".join(keyword_tokens)]
    return "\n".join(part for part in parts if part)


def deduplicate(tokens: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for token in tokens:
        normalized = token.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(normalized)
    return deduplicated


def limit_tokens(tokens: Iterable[str], *, max_n: int) -> list[str]:
    if max_n <= 0:
        return []
    return list(tokens)[:max_n]


def extract_zh_tokens(text: str) -> list[str]:
    if not _CJK_RE.search(text):
        return []
    tokens: list[str] = []
    for token in jieba.cut(text, cut_all=False):
        normalized = token.strip()
        if len(normalized) < 2:
            continue
        if not _CJK_RE.search(normalized):
            continue
        if all(char in _PUNCTUATION for char in normalized):
            continue
        tokens.append(normalized)
    return tokens


def extract_keyword_tokens(text: str) -> list[str]:
    return [match.group(0) for match in _KEYWORD_RE.finditer(text)]
