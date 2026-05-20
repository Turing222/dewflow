"""Embedding models config schema.

职责：定义 llm/models.yaml 中 embeddings 段的 Pydantic schema 及校验。
边界：本模块不创建 embedder 客户端，不解析 API key 环境变量。
失败处理：default_profile 缺失、alias 冲突时抛出 ValidationError。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.config.schemas._validators import (
    check_alias_conflicts,
    validate_non_empty_string,
    validate_unique_non_empty_list,
)


class EmbeddingModelProfile(BaseModel):
    """单个 embedding provider profile。"""

    provider: str
    model: str
    base_url: str | None = None
    api_key_envs: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    dimensions: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("provider", "model")
    @classmethod
    def validate_required_string(cls, value: str) -> str:
        return validate_non_empty_string(value)

    @field_validator("aliases", "api_key_envs")
    @classmethod
    def validate_string_list(cls, values: list[str]) -> list[str]:
        return validate_unique_non_empty_list(values)


class EmbeddingModelsConfig(BaseModel):
    """embedding profile 配置集合。"""

    default_profile: str
    profiles: dict[str, EmbeddingModelProfile]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_profiles(self) -> "EmbeddingModelsConfig":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"embedding default_profile {self.default_profile!r} is not defined "
                "in profiles"
            )

        check_alias_conflicts(self.profiles, label="Embedding profile")

        return self
