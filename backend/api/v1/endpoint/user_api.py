import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from backend.api.dependencies import (
    get_audit_service,
    get_current_active_user,
    get_current_superuser,
    get_user_import_service,
    get_user_service,
)
from backend.core.exceptions import app_bad_request, app_not_found
from backend.models.orm.user import User
from backend.models.schemas.user_schema import (
    UserCreate,
    UserImportResponse,
    UserResponse,
    UserSearch,
    UserUpdate,
)
from backend.services.audit_service import AuditAction, AuditService, capture_audit
from backend.services.user_import_service import UserImportService
from backend.services.user_service import UserService

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
SuperUserDep = Annotated[User, Depends(get_current_superuser)]
UpFile = Annotated[UploadFile, File()]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
UserImportServiceDep = Annotated[UserImportService, Depends(get_user_import_service)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get("/me", response_model=UserResponse)
async def read_users_me(
    current_user: CurrentUserDep,
) -> UserResponse:
    user_resp_data = UserResponse.model_validate(current_user)
    return user_resp_data


@router.get("", response_model=UserResponse)
async def read_user(
    search_params: Annotated[UserSearch, Depends()],
    _: SuperUserDep,
    user_service: UserServiceDep,
) -> UserResponse:
    """
    通过用户名或邮箱查询单个用户。
    DBA 视角：后端会根据参数存在与否，决定走 USERNAME 还是 EMAIL 的唯一索引。
    """
    async with user_service.uow:
        if search_params.username:
            user = await user_service.get_by_username(search_params.username)
        elif search_params.email:
            user = await user_service.get_by_email(search_params.email)
        else:
            raise app_bad_request(
                "必须提供用户名或邮箱",
                code="USER_SEARCH_PARAM_REQUIRED",
            )

        if not user:
            raise app_not_found("用户不存在", code="USER_NOT_FOUND")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    user_in: UserUpdate,
    current_user: SuperUserDep,
    user_service: UserServiceDep,
    audit_service: AuditServiceDep,
) -> UserResponse:
    """
    局部更新用户信息。
    """
    async with capture_audit(
        audit_service,
        action=AuditAction.USER_UPDATE,
        actor_user_id=current_user.id,
        resource_type="user",
        resource_id=user_id,
        metadata={"updated_fields": list(user_in.model_fields_set)},
    ):
        async with user_service.uow:
            updated_user = await user_service.user_update(
                user_id=user_id, user_in=user_in
            )
            if not updated_user:
                raise app_not_found("用户不存在", code="USER_NOT_FOUND")
        return UserResponse.model_validate(updated_user)


@router.post("", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    current_user: SuperUserDep,
    user_service: UserServiceDep,
    audit_service: AuditServiceDep,
) -> UserResponse:
    async with capture_audit(
        audit_service,
        action=AuditAction.USER_CREATE,
        actor_user_id=current_user.id,
        resource_type="user",
        metadata={"username": user_in.username, "email": user_in.email},
    ) as audit:
        async with user_service.uow:
            user = await user_service.user_register_with_personal_workspace(user_in)
            if not user:
                raise app_bad_request("用户创建失败", code="USER_CREATION_FAILED")
            audit.set_resource(resource_id=user.id)
            return UserResponse.model_validate(user)


@router.post("/csv_upload", response_model=UserImportResponse)
async def csv_balk_insert_users(
    file: UpFile,
    current_user: SuperUserDep,
    import_service: UserImportServiceDep,
    audit_service: AuditServiceDep,
) -> UserImportResponse:
    async with capture_audit(
        audit_service,
        action=AuditAction.USER_IMPORT_CSV,
        actor_user_id=current_user.id,
        resource_type="user",
        metadata={"filename": getattr(file, "filename", None)},
    ) as audit:
        async with import_service.uow:
            result = await import_service.import_from_upload(file)
            audit.add_metadata(
                total_rows=result.total_rows,
                imported_rows=result.imported_rows,
            )
            return result
