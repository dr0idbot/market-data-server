import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


def require_app_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency enforcing the shared APP_TOKEN.

    The requester must send `Authorization: Bearer <APP_TOKEN>` where APP_TOKEN
    matches the token configured via the APP_TOKEN env var. Uses a constant-time
    comparison.
    """
    valid = credentials is not None and secrets.compare_digest(
        credentials.credentials, settings.app_token
    )
    if not valid:
        request.state.auth_failure = True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Forbidden"},
            headers={"WWW-Authenticate": "Bearer"},
        )
