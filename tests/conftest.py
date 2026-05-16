"""Global pytest fixtures and test-safe environment setup.

Keep this file lightweight and avoid importing FastAPI app here.
Fixtures that require app startup should live in tests/integration/conftest.py.
"""

import os

import pytest


def pytest_configure():
    """Normalize env before test collection imports backend settings."""
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture(autouse=True)
def stable_token_counter(monkeypatch):
    """Keep token counting local and deterministic in tests."""
    from backend.ai.core import token_counter

    token_counter._encoding_cache.clear()
    monkeypatch.setattr(token_counter, "_tiktoken_available", False)
    yield
    token_counter._encoding_cache.clear()
