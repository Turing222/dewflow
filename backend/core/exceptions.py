"""Application exception classes — framework-agnostic.

职责：定义统一业务异常类和工厂函数，供 web 和 worker 层共用。
边界：不含任何 FastAPI/Starlette 依赖，worker 可直接使用。
副作用：无。
"""

from typing import Any


class AppException(Exception):
    """可映射为统一 HTTP 错误响应的业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def app_bad_request(
    message: str,
    *,
    code: str = "BAD_REQUEST",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 400 Bad Request 业务异常。"""
    return AppException(code=code, message=message, status_code=400, details=details)


def app_validation_error(
    message: str,
    *,
    code: str = "VALIDATION_ERROR",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 422 Validation Error 业务异常。"""
    return AppException(code=code, message=message, status_code=422, details=details)


def app_unauthorized(
    message: str,
    *,
    code: str = "UNAUTHORIZED",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 401 Unauthorized 业务异常。"""
    return AppException(code=code, message=message, status_code=401, details=details)


def app_forbidden(
    message: str,
    *,
    code: str = "PERMISSION_DENIED",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 403 Forbidden 业务异常。"""
    return AppException(code=code, message=message, status_code=403, details=details)


def app_not_found(
    message: str,
    *,
    code: str = "RESOURCE_NOT_FOUND",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 404 Not Found 业务异常。"""
    return AppException(code=code, message=message, status_code=404, details=details)


def app_payload_too_large(
    message: str,
    *,
    code: str = "PAYLOAD_TOO_LARGE",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 413 Payload Too Large 业务异常。"""
    return AppException(code=code, message=message, status_code=413, details=details)


def app_too_many_requests(
    message: str,
    *,
    code: str = "TOO_MANY_REQUESTS",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 429 Too Many Requests 业务异常。"""
    return AppException(code=code, message=message, status_code=429, details=details)


def app_service_error(
    message: str,
    *,
    code: str = "SERVICE_ERROR",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 500 Service Error 业务异常。"""
    return AppException(code=code, message=message, status_code=500, details=details)


def app_dependency_unavailable(
    message: str,
    *,
    code: str = "DEPENDENCY_UNAVAILABLE",
    details: dict[str, Any] | None = None,
) -> AppException:
    """创建 503 Dependency Unavailable 业务异常。"""
    return AppException(code=code, message=message, status_code=503, details=details)
