"""Base response schema every endpoint must return.

Shape:
    {
      "data": ...,
      "metadata": {...},          # always present
      "pagination": {...} | null  # present for list endpoints
      "error": null | {...}       # present on failures
    }
"""
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Query, Request
from pydantic import BaseModel, Field

API_VERSION = "1.0.0"
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


class ResponseMetadata(BaseModel):
    request_id: str = Field(description="Echoed in the X-Request-ID response header.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    service: str
    api_version: str = API_VERSION
    duration_ms: float | None = None


class PaginationMetadata(BaseModel):
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    first_index: int = Field(ge=0, description="Index (0-based) of the first returned item.")
    has_next: bool
    has_prev: bool

    @property
    def offset(self) -> int:
        return self.first_index


class PageParams(BaseModel):
    """Standard paging query params: ?page=1&page_size=25"""

    page: int = Field(
        default=1,
        ge=1,
        description="1-based page number.",
    )
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Items per page (max {MAX_PAGE_SIZE}).",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


PageParamsQuery = Annotated[PageParams, Query()]


class ErrorDetail(BaseModel):
    code: str = Field(examples=["unauthorized", "not_found"])
    message: str
    details: list[str] | None = None


class BaseResponse[T](BaseModel):
    data: T | None = None
    metadata: ResponseMetadata
    pagination: PaginationMetadata | None = None
    error: ErrorDetail | None = None


class ErrorResponse(BaseModel):
    data: None = None
    metadata: ResponseMetadata
    pagination: PaginationMetadata | None = None
    error: ErrorDetail | None = None


def build_metadata(request: Request) -> ResponseMetadata:
    settings = request.app.state.settings
    duration_ms = getattr(request.state, "duration_ms", None)
    return ResponseMetadata(
        request_id=getattr(request.state, "request_id", None) or uuid4().hex,
        service=settings.app_name,
        duration_ms=duration_ms,
    )


def build_pagination(page: PageParams, total_items: int) -> PaginationMetadata:
    total_pages = -(-total_items // page.page_size)
    return PaginationMetadata(
        total_items=total_items,
        total_pages=total_pages,
        page=page.page,
        page_size=page.page_size,
        first_index=page.offset,
        has_next=page.page < total_pages,
        has_prev=page.page > 1,
    )
