import logging
import time
import uuid

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging import log_with_extra

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request: method, path, status, duration and request id.

    Assigns/propagates a request id (X-Request-ID) and echoes it back on every
    response so callers can correlate logs.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log_with_extra(
                logger,
                logging.ERROR,
                f"{request.method} {path} failed",
                request_id=request_id,
                duration_ms=duration_ms,
                error=type(exc).__name__,
            )
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        log_with_extra(
            logger,
            logging.INFO,
            f"{request.method} {path} -> {response.status_code}",
            request_id=request_id,
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client=request.headers.get("X-Forwarded-For")
            or (request.client.host if request.client else "-"),
        )
        return response


def add_request_logging(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)
