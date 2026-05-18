"""Langfuse tracing helpers.

职责：封装 Langfuse trace metadata 绑定和 generation span 创建。
边界：本模块知道 Langfuse SDK，也知道它借 OTel context propagation 工作；trace_utils.py 不知道 Langfuse 存在。
失败处理：无参数时 no-op；有参数时懒导入 langfuse，先 get_client() 确保 SDK 初始化。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any


@contextmanager
def set_langfuse_trace_metadata(
    *,
    user_id: Any | None = None,
    session_id: Any | None = None,
    tags: Sequence[str] | None = None,
) -> Iterator[None]:
    """绑定 Langfuse trace 级属性 (user_id / session_id / tags) 到当前 OTel context。

    无参数时 no-op；有参数时懒导入 langfuse，先 get_client() 确保 SDK 初始化，
    再进入 propagate_attributes(...) 使所有子 span 继承这些属性。
    """
    if user_id is None and session_id is None and not tags:
        yield
        return

    from langfuse import get_client, propagate_attributes

    get_client()
    with propagate_attributes(
        user_id=str(user_id) if user_id else None,
        session_id=str(session_id) if session_id else None,
        tags=list(tags) if tags else None,
    ):
        yield


@contextmanager
def langfuse_generation(
    *,
    name: str,
    input_payload: Any | None = None,
) -> Iterator[None]:
    """创建 Langfuse generation observation。"""
    from langfuse import get_client

    with get_client().start_as_current_generation(
        name=name,
        input=input_payload,
    ):
        yield
