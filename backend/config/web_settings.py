"""Web / HTTP API settings.

职责：管理 FastAPI 应用的路由、鉴权、限流等 Web-only 配置。
边界：不包含 DB/Redis/Storage 等基础设施配置，不包含 AI/LLM 模型配置。
副作用：导入时加载 *_FILE secret 到环境变量。
"""

import os
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from backend.config.ai_settings import _env_files

DEFAULT_SECRET_KEY = "local-dev-secret"  # noqa: S105
PRODUCTION_APP_ENVS = {"prod", "production"}
PRODUCTION_CORS_METHODS = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
PRODUCTION_CORS_HEADERS = ["Authorization", "Content-Type", "X-Request-ID"]


def _current_app_env() -> str:
    return os.getenv("APP_ENV", "local").strip().lower() or "local"


def _default_cors_methods() -> list[str]:
    if _current_app_env() in PRODUCTION_APP_ENVS:
        return PRODUCTION_CORS_METHODS.copy()
    return ["*"]


def _default_cors_headers() -> list[str]:
    if _current_app_env() in PRODUCTION_APP_ENVS:
        return PRODUCTION_CORS_HEADERS.copy()
    return ["*"]


def _cors_defaults_for_env(app_env: str) -> tuple[list[str], list[str]]:
    if app_env.strip().lower() in PRODUCTION_APP_ENVS:
        return PRODUCTION_CORS_METHODS.copy(), PRODUCTION_CORS_HEADERS.copy()
    return ["*"], ["*"]


class WebSettings(BaseSettings):
    """Web API 配置 —— 路由、鉴权、限流。"""

    # ── App Metadata ──────────────────────────────────────────────
    PROJECT_NAME: str = "Dewflow AI"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_ROOT_PATH: str = "/api"
    API_V1_STR: str = "/v1"

    # ── Auth ──────────────────────────────────────────────────────
    SECRET_KEY: str = Field(DEFAULT_SECRET_KEY, min_length=1)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_TRUSTED_PROXY_CIDRS: str = ""
    CHAT_RATE_LIMIT_TIMES: int = 10
    CHAT_RATE_LIMIT_SECONDS: int = 60

    # ── CORS ──────────────────────────────────────────────────────
    BACKEND_CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=list)
    BACKEND_CORS_METHODS: Annotated[list[str], NoDecode] = Field(
        default_factory=_default_cors_methods
    )
    BACKEND_CORS_HEADERS: Annotated[list[str], NoDecode] = Field(
        default_factory=_default_cors_headers
    )

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def apply_environment_cors_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        app_env = str(values.get("APP_ENV") or _current_app_env())
        default_methods, default_headers = _cors_defaults_for_env(app_env)
        values.setdefault("BACKEND_CORS_METHODS", default_methods)
        values.setdefault("BACKEND_CORS_HEADERS", default_headers)
        return values

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return value

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            val = value.strip().lower()
            if val == "release":
                return False
            if val == "debug":
                return True
        return value

    @field_validator(
        "BACKEND_CORS_ORIGINS",
        "BACKEND_CORS_METHODS",
        "BACKEND_CORS_HEADERS",
        mode="before",
    )
    @classmethod
    def parse_cors_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                # 空字符串 → []，语义上是禁用所有方法/头/源。
                # 如果你想用默认值而不是禁用到所有，请直接不设这个 env var。
                return []
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


@lru_cache
def get_web_settings() -> WebSettings:
    return WebSettings()
