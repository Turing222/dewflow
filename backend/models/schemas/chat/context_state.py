"""Chat context state schemas.

职责：定义会话级轻量记忆状态，用于 Prompt 上下文和后续乐观锁更新。
边界：本模块不负责抽取、合并或持久化策略；只描述可序列化的数据契约。
"""

from pydantic import BaseModel, Field


class ContextState(BaseModel):
    """会话级对话状态。"""

    user_goal: str = ""
    current_focus: str = ""
    decisions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
    version: int = 0
    schema_version: int = 1

    def has_memory(self) -> bool:
        """Return true when the state has content useful for Prompt injection."""
        return any(
            (
                self.user_goal.strip(),
                self.current_focus.strip(),
                self.decisions,
                self.constraints,
                self.preferences,
            )
        )

    def to_prompt_dict(self) -> dict[str, object]:
        """Serialize non-versioned state for template-side Prompt rendering."""
        if not self.has_memory():
            return {}
        payload: dict[str, object] = {}
        if self.user_goal.strip():
            payload["user_goal"] = self.user_goal.strip()
        if self.current_focus.strip():
            payload["current_focus"] = self.current_focus.strip()
        if self.decisions:
            payload["decisions"] = self.decisions
        if self.constraints:
            payload["constraints"] = self.constraints
        if self.preferences:
            payload["preferences"] = self.preferences
        return payload

    def to_storage_dict(self) -> dict[str, object]:
        """Serialize state without the external optimistic-lock version."""
        return self.model_dump(mode="json", exclude={"version"})
