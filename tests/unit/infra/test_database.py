"""Database instrumentation unit tests.

职责：验证 SQLAlchemy engine instrumentation 的开关和去重逻辑；边界：使用 fake instrumentor，不创建真实数据库连接；副作用：清理模块级已 instrumented 集合。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.infra import database


class FakeInstrumentor:
    calls: list[object] = []

    def instrument(self, *, engine: object) -> None:
        self.calls.append(engine)


def test_instrument_engine_uses_sqlalchemy_instrumentor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_engine = object()
    engine = SimpleNamespace(sync_engine=sync_engine)
    FakeInstrumentor.calls = []
    database._INSTRUMENTED_ENGINE_IDS.clear()

    monkeypatch.setattr(database, "_env_flag", lambda name, default: True)
    monkeypatch.setattr(database, "SQLAlchemyInstrumentor", FakeInstrumentor)

    database._instrument_engine(engine)

    assert FakeInstrumentor.calls == [sync_engine]


def test_instrument_engine_disabled_when_otel_flag_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_engine = object()
    engine = SimpleNamespace(sync_engine=sync_engine)
    FakeInstrumentor.calls = []
    database._INSTRUMENTED_ENGINE_IDS.clear()

    monkeypatch.setattr(database, "_env_flag", lambda name, default: False)
    monkeypatch.setattr(database, "SQLAlchemyInstrumentor", FakeInstrumentor)

    database._instrument_engine(engine)

    assert FakeInstrumentor.calls == []


def test_instrument_engine_skips_duplicate_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_engine = object()
    engine = SimpleNamespace(sync_engine=sync_engine)
    FakeInstrumentor.calls = []
    database._INSTRUMENTED_ENGINE_IDS.clear()

    monkeypatch.setattr(database, "_env_flag", lambda name, default: True)
    monkeypatch.setattr(database, "SQLAlchemyInstrumentor", FakeInstrumentor)

    database._instrument_engine(engine)
    database._instrument_engine(engine)

    assert FakeInstrumentor.calls == [sync_engine]
