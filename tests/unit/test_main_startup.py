from __future__ import annotations

import importlib
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


def _fresh_main_module():
    sys.modules.pop("backend.main", None)
    return importlib.import_module("backend.main")


def test_importing_main_does_not_setup_logging(monkeypatch):
    calls: list[str] = []

    def fake_setup_logging() -> None:
        calls.append("setup")

    monkeypatch.setattr(
        "backend.observability.logger.setup_logging", fake_setup_logging
    )

    _fresh_main_module()

    assert calls == []


@pytest.mark.asyncio
async def test_lifespan_sets_up_logging_first(monkeypatch):
    events: list[str] = []
    main = _fresh_main_module()

    @asynccontextmanager
    async def fake_init_db(app):
        events.append("db")
        yield

    async def fake_redis_init():
        events.append("redis_init")

    async def fake_redis_close():
        events.append("redis_close")

    monkeypatch.setattr(main, "setup_logging", lambda: events.append("logging"))
    monkeypatch.setattr(main, "get_permission_policy", lambda: events.append("policy"))
    monkeypatch.setattr(main, "validate_llm_configs", lambda: events.append("llm"))
    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(
        main,
        "redis_client",
        SimpleNamespace(init=fake_redis_init, close=fake_redis_close),
    )
    monkeypatch.setattr(main, "shutdown_telemetry", lambda: events.append("shutdown"))

    async with main.lifespan(SimpleNamespace()):
        events.append("yielded")

    assert events == [
        "logging",
        "policy",
        "llm",
        "db",
        "redis_init",
        "yielded",
        "redis_close",
        "shutdown",
    ]
