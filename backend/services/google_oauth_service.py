"""Google OAuth2 service.

职责：构建 Google 授权 URL、交换授权码换取令牌、解析 ID Token。
边界：本模块不处理用户查找或 JWT 签发，仅负责与 Google OAuth2 交互。
"""

import logging
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
_SCOPES = "openid email profile"


class GoogleOAuthService:
    """Google OAuth2 认证服务。"""

    def __init__(self, google_client_id: str, google_client_secret: str) -> None:
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    def get_authorization_url(self, redirect_uri: str) -> str:
        """构建 Google OAuth2 授权跳转 URL。"""
        params = {
            "client_id": self._google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """用授权码换取 Google 令牌并解析 ID Token 声明。

        Returns:
            包含 sub、email、name 等字段的字典。
        """
        async with httpx.AsyncClient(timeout=10) as client:
            # 1. 用授权码换令牌
            token_resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._google_client_id,
                    "client_secret": self._google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()

        id_token = token_data.get("id_token")
        if not id_token:
            msg = "Google OAuth 响应中缺少 id_token"
            raise ValueError(msg)

        # 2. 验证 ID Token（MVP: 使用 Google tokeninfo 端点）
        claims = await self._verify_id_token(id_token)
        return claims

    async def _verify_id_token(self, id_token: str) -> dict:
        """通过 Google tokeninfo 端点验证 ID Token。

        生产环境应改为本地 JWKS 验证以减少外部依赖。
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _GOOGLE_TOKENINFO_URL,
                params={"id_token": id_token},
            )
            resp.raise_for_status()
            claims = resp.json()

        # 校验 audience 是否匹配本应用
        if claims.get("aud") != self._google_client_id:
            msg = "Google ID Token audience 不匹配"
            raise ValueError(msg)

        return {
            "sub": claims["sub"],
            "email": claims.get("email"),
            "name": claims.get("name"),
        }
