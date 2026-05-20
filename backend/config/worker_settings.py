"""Worker execution settings.

职责：管理 TaskIQ worker 进程的并发、限流和运行时行为。
边界：不包含 AI/LLM/RAG 模型配置（ai_settings），不包含 Web/HTTP 配置（web_settings）。
副作用：导入时加载 *_FILE secret 到环境变量。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.config.ai_settings import _env_files


class WorkerSettings(BaseSettings):
    """Worker 执行配置 —— worker 并发与 DB 并发。"""

    # ── LLM Concurrency ────────────────────────────────────────────
    LLM_MAX_CONCURRENCY: int = 5

    # ── DB Concurrency ─────────────────────────────────────────────
    DB_MAX_CONCURRENCY: int = 10

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
