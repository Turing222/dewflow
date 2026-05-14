from backend.models.schemas.chat.context_state import ContextState


def test_context_state_defaults_to_empty_memory():
    state = ContextState()

    assert state.decisions == []
    assert state.constraints == []
    assert state.preferences == []
    assert state.version == 0
    assert state.schema_version == 1
    assert not state.has_memory()


def test_context_state_storage_dict_excludes_version():
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


def test_context_state_prompt_dict_excludes_versions():
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


def test_context_state_prompt_dict_strips_blank_text_fields():
    state = ContextState(
        user_goal="  ",
        current_focus="  RAG 策略  ",
        decisions=["使用会话级状态"],
    )

    payload = state.to_prompt_dict()

    assert "user_goal" not in payload
    assert payload["current_focus"] == "RAG 策略"
    assert payload["decisions"] == ["使用会话级状态"]
