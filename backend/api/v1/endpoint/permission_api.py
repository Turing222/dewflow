from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_current_active_user, get_permission_service
from backend.models.orm.user import User
from backend.models.schemas.permission_schema import PermissionPolicyResponse
from backend.services.permission_service import PermissionService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
PermissionServiceDep = Annotated[PermissionService, Depends(get_permission_service)]


@router.get("/policy")
async def get_permission_policy_metadata(
    _: CurrentUserDep,
    permission_service: PermissionServiceDep,
) -> PermissionPolicyResponse:
    return permission_service.get_policy_response()
