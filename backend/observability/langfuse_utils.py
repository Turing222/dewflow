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


class _LangfuseGenerationRecorder:
    """Langfuse generation 后置更新包装器。

    调用方通过 record() 延迟写入 output / usage / metadata / model / error，
    上下文退出时 Langfuse SDK 自动调用 generation.end()。
    """

    __slots__ = ("_generation",)

    def __init__(self, generation: Any) -> None:
        self._generation = generation

    def record(
        self,
        *,
        output: Any | None = None,
        usage: dict[str, int] | None = None,
        metadata: Any | None = None,
        model: str | None = None,
        error: str | None = None,
    ) -> None:
        update_kwargs: dict[str, Any] = {}
        if output is not None:
            update_kwargs["output"] = output
        if usage is not None:
            update_kwargs["usage_details"] = usage
        if metadata is not None:
            update_kwargs["metadata"] = metadata
        if model is not None:
            update_kwargs["model"] = model
        if error is not None:
            update_kwargs["status_message"] = error
            update_kwargs["level"] = "ERROR"
        if update_kwargs:
            self._generation.update(**update_kwargs)


@contextmanager
def langfuse_generation(
    *,
    name: str,
    input_payload: Any | None = None,
    model: str | None = None,
    metadata: Any | None = None,
) -> Iterator[_LangfuseGenerationRecorder]:
    """创建 Langfuse generation observation，返回 recorder 供后置更新。

    正常退出时 Langfuse SDK 自动调用 generation.end()；
    异常时 recorder 自动记录 error 后重新抛出。
    """
    from langfuse import get_client

    create_kwargs: dict[str, Any] = {"name": name}
    if input_payload is not None:
        create_kwargs["input"] = input_payload
    if model is not None:
        create_kwargs["model"] = model
    if metadata is not None:
        create_kwargs["metadata"] = metadata

    with get_client().start_as_current_generation(**create_kwargs) as generation:
        recorder = _LangfuseGenerationRecorder(generation)
        try:
            yield recorder
        except Exception as exc:
            recorder.record(error=str(exc))
            raise
