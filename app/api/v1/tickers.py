"""Single-symbol market data routes: metadata + OHLCV (paginated, descending)."""

from __future__ import annotations

import logging
import traceback
from typing import Annotated, Any, NoReturn

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from app.api.deps import authed_request
from app.core.logging import log_with_extra
from app.schemas.base import BaseResponse, PaginationMetadata, build_metadata
from app.schemas.market import MetadataData, OhlcvData
from app.services import yahoo

logger = logging.getLogger("app.api.tickers")

router = APIRouter(
    prefix="/ticker",
    tags=["market-data"],
    dependencies=[authed_request],
)


def _raise_for_yahoo(exc: yahoo.YahooError, context: str) -> NoReturn:
    """Yahoo failure -> enveloped HTTP error; raw chain + traceback included."""
    raise HTTPException(
        status_code=exc.http_status,
        detail={
            "code": exc.code,
            "message": f"{context}: {exc}",
            "details": exc.details(),
        },
    )


def _ohlcv_pagination(page: int, page_size: int, total_items: int) -> PaginationMetadata:
    total_pages = -(-total_items // page_size) if total_items else 0
    first_index = (page - 1) * page_size
    return PaginationMetadata(
        total_items=total_items,
        total_pages=total_pages,
        page=page,
        page_size=page_size,
        first_index=first_index,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def _history_or_empty(
    symbol: str,
    interval: str,
    period: str | None,
    start: str | None,
    end: str | None,
    auto_adjust: bool,
    context: str,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    """history(), or (None, {}) for valid symbols that simply have no rows."""
    try:
        return yahoo.fetch_ohlcv(symbol, interval, period, start, end, auto_adjust=auto_adjust)
    except yahoo.YahooError as exc:
        if isinstance(exc, yahoo.YahooNotFound):
            try:
                info, _ = yahoo.fetch_metadata(symbol)
                if info:
                    log_with_extra(
                        logger,
                        logging.INFO,
                        f"{context}: symbol valid, no rows in window -> empty result",
                        symbol=symbol,
                    )
                    return None, {}
            except yahoo.YahooError:
                pass
        log_with_extra(logger, logging.ERROR, f"{context} failed", symbol=symbol)
        _raise_for_yahoo(exc, context)


@router.get(
    "/{symbol}/metadata",
    summary="Complete metadata for one Yahoo symbol",
    response_model=BaseResponse[MetadataData],
)
def ticker_metadata(
    symbol: str,
    request: Request,
    extended: Annotated[
        bool, Query(description="Include the full raw Yahoo info payload as `data.raw`")
    ] = False,
) -> BaseResponse[MetadataData]:
    canonical = yahoo.validate_symbol(symbol)
    context = f"fetching metadata for {canonical}"
    try:
        info, isin = yahoo.fetch_metadata(canonical)
    except yahoo.YahooError as exc:
        log_with_extra(logger, logging.ERROR, f"{context} failed", symbol=canonical)
        _raise_for_yahoo(exc, context)

    data = yahoo.build_metadata_data(info, canonical, isin)
    if extended:
        data.raw = yahoo.sanitize_json(info)
    return BaseResponse[MetadataData](data=data, metadata=build_metadata(request))


@router.get(
    "/{symbol}/ohlcv",
    summary="OHLCV bars for one Yahoo symbol (paginated, latest first)",
    response_model=BaseResponse[OhlcvData],
)
def ticker_ohlcv(
    symbol: str,
    request: Request,
    interval: Annotated[str, Query()] = "1d",
    range: Annotated[str | None, Query()] = None,
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
    adjust: Annotated[bool, Query()] = True,
    tz: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 252,
) -> BaseResponse[OhlcvData]:
    canonical = yahoo.validate_symbol(symbol)
    period, start, end, echoed_range = yahoo.resolve_ohlcv_params(
        interval, range, start_date, end_date
    )
    settings = request.app.state.settings
    page_size = min(page_size, settings.ohlcv_page_size_max)
    if tz is not None:
        yahoo.validate_tz(tz)
    context = f"fetching {interval} OHLCV for {canonical}"

    df, meta = _history_or_empty(canonical, interval, period, start, end, adjust, context)
    frame = df if df is not None else pd.DataFrame()
    try:
        points, newest, oldest = yahoo.history_points(frame, interval, tz)
    except yahoo.YahooError as exc:
        _raise_for_yahoo(exc, context)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected non-upstream failure: %s", context)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_unavailable",
                "message": f"{context}: unexpected processing failure: {exc}",
                "details": [
                    f"{type(exc).__name__}: {exc}",
                    "traceback:\n" + traceback.format_exc(),
                ],
            },
        ) from exc
    log_with_extra(
        logger,
        logging.INFO,
        f"{context} ok",
        symbol=canonical,
        rows=len(points),
        page=page,
        page_size=page_size,
    )
    offset = (page - 1) * page_size
    data = OhlcvData(
        symbol=canonical,
        name=meta.get("shortName") or meta.get("longName") or None,
        quote_type=meta.get("instrumentType"),
        currency=meta.get("currency"),
        timezone=meta.get("timezone"),
        adjusted=adjust,
        newest=newest,
        oldest=oldest,
        observations=points[offset : offset + page_size],
        interval=interval,
        range=echoed_range,
        requested_start=start,
        requested_end=end,
    )
    return BaseResponse[OhlcvData](
        data=data,
        metadata=build_metadata(request),
        pagination=_ohlcv_pagination(page, page_size, len(points)),
    )
