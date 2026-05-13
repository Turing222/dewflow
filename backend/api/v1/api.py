from fastapi import APIRouter, Depends

from backend.api.v1.endpoint import (
    audit_api,
    auth_api,
    chat_api,
    health_check,
    knowledge_api,
    permission_api,
    user_api,
    workspace_api,
)
from backend.middleware.rate_limit import RateLimiter

api_router = APIRouter()

api_router.include_router(
    auth_api.router,
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
api_router.include_router(
    user_api.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(RateLimiter(times=100, seconds=60))],
)
api_router.include_router(chat_api.router, prefix="/chat", tags=["chat"])
api_router.include_router(
    knowledge_api.router,
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(RateLimiter(times=100, seconds=60))],
)
api_router.include_router(
    audit_api.router,
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(RateLimiter(times=100, seconds=60))],
)
api_router.include_router(
    workspace_api.router,
    prefix="/workspaces",
    tags=["workspaces"],
    dependencies=[Depends(RateLimiter(times=100, seconds=60))],
)
api_router.include_router(
    permission_api.router,
    prefix="/permissions",
    tags=["permissions"],
    dependencies=[Depends(RateLimiter(times=100, seconds=60))],
)
api_router.include_router(
    health_check.router, prefix="/health_check", tags=["health_check"]
)
