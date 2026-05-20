from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_audit_service, get_login_data, get_user_service
from backend.config.settings import settings
from backend.core.exceptions import app_bad_request
from backend.core.security import create_access_token
from backend.middleware.rate_limit import RateLimiter
from backend.models.enums import AuditOutcome
from backend.models.schemas.user_schema import (
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from backend.services.audit_service import AuditAction, AuditService, record_audit
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
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
LoginDataDep = Annotated[UserLogin, Depends(get_login_data)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


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
