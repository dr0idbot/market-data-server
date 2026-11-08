"""Custom exception handlers so *every* response (including errors)
follows the base schema envelope."""
import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.base import ErrorDetail, ErrorResponse, build_metadata

logger = logging.getLogger("app.error")


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[str] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        metadata=build_metadata(request),
        error=ErrorDetail(code=code, message=message, details=details),
    )
    response = JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers=dict(headers) if headers else None,
    )
    if getattr(request.state, "request_id", None):
        response.headers["X-Request-ID"] = request.state.request_id
    return response


def add_error_handlers(app: FastAPI) -> None:
    # Keyed on starlette's base so both starlette's and FastAPI's
    # HTTPException subclasses match.
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            code = str(detail.get("code", "error"))
            message = str(detail.get("message", "Request failed"))
            details = detail.get("details")
            details = [str(d) for d in details] if details else None
        else:
            code, message, details = "error", str(detail or "Request failed"), None
        auth_failure = getattr(request.state, "auth_failure", False)
        level = logger.warning if auth_failure or exc.status_code >= 500 else logger.info
        level(
            "%s %s -> %s (%s)",
            request.method,
            request.url.path,
            exc.status_code,
            message,
        )
        return _error_response(
            request,
            exc.status_code,
            code=code,
            message=message,
            details=details,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            f"{'/'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        ]
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            message="Request validation failed",
            details=details,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error on %s %s", request.method, request.url.path, exc_info=exc
        )
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="Internal server error",
        )
