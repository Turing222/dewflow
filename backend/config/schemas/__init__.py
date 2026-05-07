"""Config schema definitions — Pydantic models for YAML config validation.

职责：验证 YAML 配置文件的完整性和一致性。
边界：本包不读取文件、不访问环境变量，只验证传入的配置结构。
向后兼容：所有顶层 schema 类从此 __init__.py 统一 re-export。
"""

from backend.config.schemas.embeddings import (
    EmbeddingModelProfile,
    EmbeddingModelsConfig,
)
from backend.config.schemas.models import (
    LLMModelProfile,
    LLMModelRoute,
    LLMModelsConfig,
)
from backend.config.schemas.permissions import (
    PermissionDefaults,
    PermissionDefinition,
    PermissionsConfig,
    RoleDefinition,
)
from backend.config.schemas.prompts import (
    LangfusePromptConfig,
    LangfusePromptDefinition,
    PromptDefaults,
    PromptsConfig,
    PromptSource,
    PromptTemplateDefinition,
)

__all__ = [
    "EmbeddingModelProfile",
    "EmbeddingModelsConfig",
    "LangfusePromptConfig",
    "LangfusePromptDefinition",
    "LLMModelProfile",
    "LLMModelRoute",
    "LLMModelsConfig",
    "PermissionDefaults",
    "PermissionDefinition",
    "PermissionsConfig",
    "PromptDefaults",
    "PromptsConfig",
    "PromptSource",
    "PromptTemplateDefinition",
    "RoleDefinition",
]
