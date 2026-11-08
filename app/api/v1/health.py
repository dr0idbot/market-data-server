from typing import Literal

from fastapi import APIRouter, Request

from app.api.deps import authed_request
from app.schemas.base import BaseResponse, build_metadata

router = APIRouter(
    prefix="/health",
    tags=["health"],
    dependencies=[authed_request],
)

ServiceStatus = Literal["ok"]


@router.get(
    "",
    summary="Liveness / readiness",
    description="Authenticated healthcheck. Returns service status metadata.",
    response_model=BaseResponse[dict[str, str]],
)
async def healthcheck(request: Request) -> BaseResponse[dict[str, str]]:
    return BaseResponse[dict[str, str]](
        data={"status": "ok"},
        metadata=build_metadata(request),
    )
