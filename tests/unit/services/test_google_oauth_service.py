"""GoogleOAuthService unit tests.

职责：验证 Google OAuth URL 构造和 ID Token 本地验证映射；
边界：mock google-auth verifier，不访问 Google 网络；副作用：无。
"""

from __future__ import annotations

import pytest

from backend.services.google_oauth_service import GoogleOAuthService

pytestmark = pytest.mark.asyncio


async def test_verify_id_token_uses_local_google_auth_verifier(monkeypatch) -> None:
    service = GoogleOAuthService(
        google_client_id="client-id",
        google_client_secret="client-secret",
    )
    calls: dict[str, object] = {}

    def fake_verify_oauth2_token(token: str, request: object, audience: str) -> dict:
        calls["token"] = token
        calls["request"] = request
        calls["audience"] = audience
        return {
            "sub": "google-sub",
            "email": "user@example.com",
            "name": "User Name",
        }

    monkeypatch.setattr(
        "backend.services.google_oauth_service.google_id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    claims = await service._verify_id_token("id-token")

    assert claims == {
        "sub": "google-sub",
        "email": "user@example.com",
        "name": "User Name",
    }
    assert calls["token"] == "id-token"
    assert calls["audience"] == "client-id"
