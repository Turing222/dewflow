"""ContextState schema unit tests.

职责：验证 ContextState 的默认值、序列化方法和字段清洗行为；边界：直接调用 Pydantic 方法，不涉及数据库或 HTTP；副作用：无。
"""

from backend.models.schemas.chat.context_state import ContextState


def test_defaults_to_empty_memory_when_no_input() -> None:
    state = ContextState()

    assert state.decisions == []
    assert state.constraints == []
    assert state.preferences == []
    assert state.version == 0
    assert state.schema_version == 1
    assert not state.has_memory()


def test_to_storage_dict_excludes_version() -> None:
    state = ContextState(
        decisions=["使用 pgvector"],
        constraints=["回答必须中文"],
        preferences=["偏好简洁输出"],
        version=3,
    )

    payload = state.to_storage_dict()

    assert payload["decisions"] == ["使用 pgvector"]
    assert payload["constraints"] == ["回答必须中文"]
    assert payload["preferences"] == ["偏好简洁输出"]
    assert "version" not in payload


def test_to_prompt_dict_excludes_versions() -> None:
    state = ContextState(
        user_goal="完成 RAG 记忆设计",
        decisions=["使用会话级状态"],
        version=3,
        schema_version=1,
    )

    payload = state.to_prompt_dict()

    assert payload["user_goal"] == "完成 RAG 记忆设计"
    assert payload["decisions"] == ["使用会话级状态"]
    assert "version" not in payload
    assert "schema_version" not in payload


def test_to_prompt_dict_strips_blank_text_fields() -> None:
    state = ContextState(
        user_goal="  ",
        current_focus="  RAG 策略  ",
        decisions=["使用会话级状态"],
    )

    payload = state.to_prompt_dict()

    assert "user_goal" not in payload
    assert payload["current_focus"] == "RAG 策略"
    assert payload["decisions"] == ["使用会话级状态"]
