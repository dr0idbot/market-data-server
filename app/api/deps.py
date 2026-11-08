"""Shared FastAPI dependencies for API routers."""

from fastapi import Depends

from app.core.auth import require_app_token

# Attach to any APIRouter (dependencies=[authed_request]) or endpoint parameter
# that must require the APP_TOKEN bearer check.
authed_request = Depends(require_app_token)
