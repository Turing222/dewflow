from __future__ import annotations

from types import SimpleNamespace

from backend.infra import database


class FakeInstrumentor:
    calls: list[object] = []

    def instrument(self, *, engine: object) -> None:
        self.calls.append(engine)


def test_instrument_engine_uses_sqlalchemy_instrumentor(monkeypatch):
    sync_engine = object()
    engine = SimpleNamespace(sync_engine=sync_engine)
    FakeInstrumentor.calls = []
    database._INSTRUMENTED_ENGINE_IDS.clear()

    monkeypatch.setattr(database, "_env_flag", lambda name, default: True)
    monkeypatch.setattr(database, "SQLAlchemyInstrumentor", FakeInstrumentor)

    database._instrument_engine(engine)

    assert FakeInstrumentor.calls == [sync_engine]


def test_instrument_engine_skips_duplicate_engine(monkeypatch):
    sync_engine = object()
    engine = SimpleNamespace(sync_engine=sync_engine)
    FakeInstrumentor.calls = []
    database._INSTRUMENTED_ENGINE_IDS.clear()

    monkeypatch.setattr(database, "_env_flag", lambda name, default: True)
    monkeypatch.setattr(database, "SQLAlchemyInstrumentor", FakeInstrumentor)

    database._instrument_engine(engine)
    database._instrument_engine(engine)

    assert FakeInstrumentor.calls == [sync_engine]
