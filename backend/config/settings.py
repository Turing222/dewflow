"""Application settings.

职责：合并环境变量、dotenv、Docker secrets 和 YAML 配置，生成应用运行设置。
边界：本模块不创建数据库、Redis 或 LLM 客户端；只提供配置值和派生 URL。
副作用：导入时会加载受支持的 *_FILE secret 到环境变量。
"""

import logging
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import Field, field_validator
from sqlalchemy.engine import URL, make_url

from backend.config.ai_settings import BASE_DIR, AISettings, _config_dir

_logger = logging.getLogger(__name__)


class Settings(AISettings):
    """应用配置 —— 继承 AI 配置，追加 Web/DB/Redis/Auth 等基础设施字段。"""

    # ── App Metadata ──────────────────────────────────────────────
    APP_ENV: str = Field(default_factory=lambda: __import__("os").getenv("APP_ENV", "local").strip().lower() or "local")
    CONFIG_DIR: Path = Field(default_factory=_config_dir)
    BASE_DIR: Path = BASE_DIR
    LOG_DIR: Path = BASE_DIR / "logs/backend"

    PROJECT_NAME: str = "Obsidian Mentor AI"
    VERSION: str = "0.1.0"
    API_ROOT_PATH: str = "/api"
    API_V1_STR: str = "/v1"

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL: str | None = None
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mentor_ai"
    POSTGRES_DB_ECHO: bool = False
    POSTGRES_POOL_SIZE: int = 10
    POSTGRES_MAX_OVERFLOW: int = 20
    POSTGRES_SSL_MODE: str | None = None
    POSTGRES_CONNECT_TIMEOUT_SECONDS: int = Field(default=10, ge=1)

    BATCH_SIZE: int = 500

    # ── Redis ─────────────────────────────────────────────────────
    REDIS_URL: str | None = None
    TASKIQ_REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None

    # ── Storage ───────────────────────────────────────────────────
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_ROOT: Path = Path(".files/knowledge_files")
    S3_BUCKET: str | None = None
    S3_PREFIX: str = "knowledge_files"
    S3_REGION: str | None = None
    S3_ENDPOINT_URL: str | None = None
    S3_ACCESS_KEY_ID: str | None = None
    S3_SECRET_ACCESS_KEY: str | None = None

    # ── Concurrency / Rate Limiting ───────────────────────────────
    DB_MAX_CONCURRENCY: int = 10
    RATE_LIMIT_TRUSTED_PROXY_CIDRS: str = ""
    CHAT_RATE_LIMIT_TIMES: int = 10
    CHAT_RATE_LIMIT_SECONDS: int = 60

    # ── Auth ──────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., min_length=1)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # ── Properties ────────────────────────────────────────────────

    @property
    def database_url(self) -> str:
        return self._database_url_obj().render_as_string(hide_password=False)

    @property
    def database_url_safe(self) -> str:
        return self._database_url_obj().render_as_string(hide_password=True)

    @property
    def database_connect_args(self) -> dict[str, object]:
        connect_args: dict[str, object] = {
            "timeout": self.POSTGRES_CONNECT_TIMEOUT_SECONDS
        }
        ssl_mode = (self.POSTGRES_SSL_MODE or "").strip().lower()
        if ssl_mode == "disable":
            connect_args["ssl"] = False
        elif ssl_mode == "require":
            connect_args["ssl"] = True
        return connect_args

    @property
    def local_storage_root(self) -> Path:
        return self.LOCAL_STORAGE_ROOT

    def _database_url_obj(self) -> URL:
        if self.DATABASE_URL:
            return make_url(self.DATABASE_URL)
        return self._build_database_url()

    def _build_database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return self._build_redis_url(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            password=self.REDIS_PASSWORD,
            db=0,
        )

    @property
    def taskiq_redis_url(self) -> str:
        if self.TASKIQ_REDIS_URL:
            return self.TASKIQ_REDIS_URL
        if self.REDIS_URL:
            return self._replace_redis_db(self.REDIS_URL, db=1)
        return self._build_redis_url(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            password=self.REDIS_PASSWORD,
            db=1,
        )

    @staticmethod
    def _build_redis_url(
        *,
        host: str,
        port: int,
        password: str | None,
        db: int,
    ) -> str:
        auth = f":{quote(password, safe='')}@" if password else ""
        return f"redis://{auth}{host}:{port}/{db}"

    @staticmethod
    def _replace_redis_db(url: str, db: int) -> str:
        parsed = urlsplit(url)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, f"/{db}", parsed.query, parsed.fragment)
        )

    # ── Validators ────────────────────────────────────────────────

    @field_validator("STORAGE_BACKEND")
    @classmethod
    def validate_storage_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "s3"}:
            raise ValueError("STORAGE_BACKEND must be one of: local, s3")
        return normalized

    @field_validator("POSTGRES_SSL_MODE")
    @classmethod
    def validate_postgres_ssl_mode(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if normalized not in {"disable", "require"}:
            raise ValueError("POSTGRES_SSL_MODE must be one of: disable, require")
        return normalized

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("SECRET_KEY must not be empty")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
