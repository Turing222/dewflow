"""Prompts YAML config schema.

职责：定义 llm/prompts.yaml 的 Pydantic schema 及跨字段校验。
边界：本模块不编译 Jinja2 模板，不读取 Langfuse 缓存文件。
失败处理：缺少必需模板定义或 Langfuse 映射不完整时抛出 ValidationError。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.config.schemas._validators import (
    validate_non_empty_preserved_string,
    validate_non_empty_string,
)


class PromptTemplateDefinition(BaseModel):
    """Prompt 模板文本定义。"""

    content: str

    model_config = ConfigDict(extra="forbid")

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return validate_non_empty_preserved_string(value)


class PromptDefaults(BaseModel):
    """Prompt 模板默认变量。"""

    variables: dict[str, object] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class PromptSource(BaseModel):
    """Prompt 来源与缓存策略。"""

    provider: Literal["yaml", "langfuse_cache"] = "yaml"
    label: str = "production"
    ttl_seconds: int = Field(default=300, ge=0)
    cache_path: str = ".cache/langfuse/prompts.production.yaml"
    fallback: Literal["yaml", "none"] = "yaml"
    synced_at: str | None = None

    model_config = ConfigDict(extra="forbid")


class LangfusePromptDefinition(BaseModel):
    """Langfuse prompt 映射定义。"""

    name: str
    type: Literal["text", "chat"] = "text"
    version: int | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_non_empty_string(value)


class LangfusePromptConfig(BaseModel):
    """Langfuse prompt 映射集合。"""

    templates: dict[str, LangfusePromptDefinition] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class PromptsConfig(BaseModel):
    """llm/prompts.yaml 的完整 schema。"""

    version: int = 1
    source: PromptSource = Field(default_factory=PromptSource)
    langfuse: LangfusePromptConfig = Field(default_factory=LangfusePromptConfig)
    defaults: PromptDefaults = Field(default_factory=PromptDefaults)
    templates: dict[str, PromptTemplateDefinition]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_required_templates(self) -> "PromptsConfig":
        required_templates = {"default_system", "rag_system", "summarize"}
        missing_templates = required_templates - set(self.templates)
        if missing_templates:
            raise ValueError(
                f"prompts.yaml must define templates: {sorted(missing_templates)}"
            )
        if self.source.provider == "langfuse_cache":
            missing_langfuse_templates = required_templates - set(
                self.langfuse.templates
            )
            if missing_langfuse_templates:
                raise ValueError(
                    "prompts.yaml must define Langfuse mappings for templates: "
                    f"{sorted(missing_langfuse_templates)}"
                )
        return self
