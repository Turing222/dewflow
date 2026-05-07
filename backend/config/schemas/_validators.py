"""Shared field/model validators for config schemas.

职责：提供跨 schema 模块复用的 Pydantic validator 函数和 alias 冲突检测工具。
边界：本模块是纯工具函数，不依赖任何业务模型或 ORM。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


def validate_non_empty_string(value: str) -> str:
    """校验字符串非空白，返回 stripped 结果。"""
    if not value.strip():
        raise ValueError("Value must not be empty")
    return value.strip()


def validate_non_empty_preserved_string(value: str) -> str:
    """校验字符串非空白，保留原始内容。"""
    if not value.strip():
        raise ValueError("Value must not be empty")
    return value


def validate_unique_non_empty_list(values: list[str]) -> list[str]:
    """校验字符串列表：去空白、去重、去空。"""
    cleaned = [value.strip() for value in values if value.strip()]
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("Values must be unique")
    return cleaned


def check_alias_conflicts(
    entries: dict[str, Any],
    *,
    label: str = "Profile",
    get_aliases: Callable[[Any], list[str]] = lambda obj: obj.aliases,
) -> None:
    """检测 name 与 alias 的跨条目冲突。

    Args:
        entries: {name: object} 映射，每个 object 需有 .aliases 属性（或通过 get_aliases 提取）。
        label: 错误消息中的条目类型标签。
        get_aliases: 从条目提取 alias 列表的回调。

    Raises:
        ValueError: 发现空白 alias 或跨条目 alias 冲突。
    """
    seen: dict[str, str] = {}
    for name, entry in entries.items():
        identifiers = [name, *get_aliases(entry)]
        for identifier in identifiers:
            normalized = identifier.strip().lower()
            if not normalized:
                raise ValueError(f"{label} aliases must not be empty")
            existing = seen.get(normalized)
            if existing and existing != name:
                raise ValueError(
                    f"{label} alias {identifier!r} is used by both "
                    f"{existing!r} and {name!r}"
                )
            seen[normalized] = name
