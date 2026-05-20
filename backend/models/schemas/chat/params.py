"""LLM provider parameter schemas.

职责：定义可从配置或 HTTP 请求传入 LLM provider 的受控额外参数。
边界：只描述允许透传的 provider 参数，不绑定具体 SDK 或业务 workflow。
副作用：无。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LLMThinkingConfig(BaseModel):
    """Provider thinking mode control."""

    type: Literal["enabled", "disabled"]

    model_config = ConfigDict(extra="forbid")


class LLMExtraBody(BaseModel):
    """Whitelisted LLM provider-specific request body."""

    thinking: LLMThinkingConfig | None = None

    model_config = ConfigDict(extra="forbid")

    def to_provider_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)
