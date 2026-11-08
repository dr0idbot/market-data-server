from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import add_error_handlers
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_with_extra, logger
from app.core.middleware import add_request_logging
from app.schemas.base import API_VERSION


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log_with_extra(
        logger,
        20,
        f"{settings.app_name} started (env={settings.app_env})",
        env=settings.app_env,
        api_version=API_VERSION,
    )
    if settings.is_prod and settings.app_token == "change-me":  # noqa: S105 - sentinel
        log_with_extra(logger, 40, "APP_TOKEN is still the default value in prod")
    yield
    log_with_extra(logger, 20, f"{settings.app_name} shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version=API_VERSION,
        lifespan=lifespan,
        docs_url=None if settings.is_prod else "/docs",
        redoc_url=None if settings.is_prod else "/redoc",
        openapi_url=None if settings.is_prod else "/openapi.json",
    )
    app.state.settings = settings

    add_request_logging(app)
    app.include_router(api_router, prefix="/v1")
    add_error_handlers(app)
    return app


app = create_app()
