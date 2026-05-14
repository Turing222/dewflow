"""Web / HTTP API settings.

职责：管理 FastAPI 应用的路由、鉴权、限流等 Web-only 配置。
边界：不包含 DB/Redis/Storage 等基础设施配置，不包含 AI/LLM 模型配置。
副作用：导入时加载 *_FILE secret 到环境变量。
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.config.ai_settings import _env_files


class WebSettings(BaseSettings):
    """Web API 配置 —— 路由、鉴权、限流。"""

    # ── App Metadata ──────────────────────────────────────────────
    PROJECT_NAME: str = "Dewflow AI"
    VERSION: str = "0.1.0"
    DEBUG: bool = False
    API_ROOT_PATH: str = "/api"
    API_V1_STR: str = "/v1"

    # ── Auth ──────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., min_length=1)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_TRUSTED_PROXY_CIDRS: str = ""
    CHAT_RATE_LIMIT_TIMES: int = 10
    CHAT_RATE_LIMIT_SECONDS: int = 60

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return value


@lru_cache
def get_web_settings() -> WebSettings:
    return WebSettings()
