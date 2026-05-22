from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import IntegrityError

from backend.api.dependencies import get_audit_service, get_login_data, get_user_service
from backend.api.deps.services import get_google_oauth_service, get_sms_service
from backend.config.settings import settings
from backend.config.web_settings import get_web_settings
from backend.core.exceptions import app_bad_request
from backend.core.security import create_access_token
from backend.middleware.rate_limit import RateLimiter
from backend.models.enums import AuditOutcome
from backend.models.schemas.user_schema import (
    GoogleAuthUrlResponse,
    GoogleCallbackRequest,
    PhoneLoginRequest,
    SMSSendRequest,
    SMSSendResponse,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from backend.services.audit_service import AuditAction, AuditService, record_audit
from backend.services.google_oauth_service import GoogleOAuthService
from backend.services.sms_service import SMSService
from backend.services.user_service import UserService

router = APIRouter()
register_limiter = RateLimiter(
    times=settings.AUTH_REGISTER_RATE_LIMIT_TIMES,
    seconds=settings.AUTH_REGISTER_RATE_LIMIT_SECONDS,
)
login_limiter = RateLimiter(
    times=settings.AUTH_LOGIN_RATE_LIMIT_TIMES,
    seconds=settings.AUTH_LOGIN_RATE_LIMIT_SECONDS,
)
sms_limiter = RateLimiter(
    times=settings.SMS_SEND_RATE_LIMIT_TIMES,
    seconds=settings.SMS_SEND_RATE_LIMIT_SECONDS,
)
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
LoginDataDep = Annotated[UserLogin, Depends(get_login_data)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
SMSServiceDep = Annotated[SMSService, Depends(get_sms_service)]
GoogleOAuthServiceDep = Annotated[GoogleOAuthService, Depends(get_google_oauth_service)]


@router.post("/register", dependencies=[Depends(register_limiter)])
async def register(user_in: UserCreate, user_service: UserServiceDep) -> UserResponse:
    async with user_service.write():
        user = await user_service.user_register_with_personal_workspace(user_in)
    return UserResponse.model_validate(user)


@router.post("/login", dependencies=[Depends(login_limiter)])
async def login(
    login_data: LoginDataDep,
    user_service: UserServiceDep,
    audit_service: AuditServiceDep,
) -> Token:
    # 1. 调用 Service 验证
    async with user_service.write():
        user = await user_service.authenticate(login_data)
        if not user:
            await record_audit(
                audit_service,
                action=AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.FAILED,
                metadata={
                    "username": login_data.username,
                    "reason": "bad_credentials",
                },
            )
            raise app_bad_request("用户名或密码错误", code="BAD_CREDENTIALS")

        if not user.is_active:
            await record_audit(
                audit_service,
                action=AuditAction.AUTH_LOGIN_FAILED,
                actor_user_id=user.id,
                outcome=AuditOutcome.FAILED,
                metadata={
                    "username": login_data.username,
                    "reason": "inactive_user",
                },
            )
            raise app_bad_request("用户名或密码错误", code="BAD_CREDENTIALS")

    # 2. 发放 Token (Token 生成是纯 CPU 计算，无需 await)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"username": login_data.username},
    )
    return Token(access_token=access_token, token_type="bearer")  # noqa: S106


# ── SMS Verification ──────────────────────────────────────────────


@router.post("/sms/send", dependencies=[Depends(sms_limiter)])
async def sms_send(body: SMSSendRequest, sms_service: SMSServiceDep) -> SMSSendResponse:
    """发送短信验证码（mock 模式下返回验证码明文）。"""
    code = await sms_service.send_code(body.phone)
    result = SMSSendResponse(message="验证码已发送")
    if get_web_settings().SMS_MOCK_MODE:
        result.code = code
    return result


@router.post("/sms/login")
async def sms_login(
    body: PhoneLoginRequest,
    user_service: UserServiceDep,
    sms_service: SMSServiceDep,
    audit_service: AuditServiceDep,
) -> Token:
    """手机号 + 验证码登录（首次自动注册）。"""
    if not await sms_service.verify_code(body.phone, body.code):
        raise app_bad_request("验证码错误或已过期", code="INVALID_SMS_CODE")

    try:
        async with user_service.write():
            user = await user_service.find_or_create_by_phone(body.phone)
    except IntegrityError:
        # 并发注册竞态，重新查询即可。
        async with user_service.write():
            user = await user_service.find_or_create_by_phone(body.phone)

    if not user.is_active:
        raise app_bad_request("账号已停用", code="INACTIVE_USER")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_SMS_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"phone": body.phone, "auth_provider": "phone"},
    )
    return Token(access_token=access_token, token_type="bearer")  # noqa: S106


# ── Google OAuth ──────────────────────────────────────────────────


@router.get("/google/url")
async def google_auth_url(
    redirect_uri: str = Query(..., description="前端回调地址"),
    google_service: GoogleOAuthServiceDep = GoogleOAuthServiceDep,
) -> GoogleAuthUrlResponse:
    """获取 Google OAuth2 授权跳转 URL。"""
    url = google_service.get_authorization_url(redirect_uri)
    return GoogleAuthUrlResponse(url=url)


@router.post("/google/callback")
async def google_callback(
    body: GoogleCallbackRequest,
    user_service: UserServiceDep,
    google_service: GoogleOAuthServiceDep,
    audit_service: AuditServiceDep,
) -> Token:
    """用 Google 授权码换取 JWT（首次自动注册）。"""
    claims = await google_service.exchange_code(body.code, body.redirect_uri)

    try:
        async with user_service.write():
            user = await user_service.find_or_create_by_google(
                google_sub=claims["sub"],
                email=claims.get("email"),
                name=claims.get("name"),
            )
    except IntegrityError:
        # 并发注册竞态，重新查询即可。
        async with user_service.write():
            user = await user_service.find_or_create_by_google(
                google_sub=claims["sub"],
                email=claims.get("email"),
                name=claims.get("name"),
            )

    if not user.is_active:
        raise app_bad_request("账号已停用", code="INACTIVE_USER")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_GOOGLE_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"google_sub": claims["sub"], "auth_provider": "google"},
    )
    return Token(access_token=access_token, token_type="bearer")  # noqa: S106
