"""Bulk OHLCV: POST /v1/bulk/ohlcv — many symbols, one shared window."""

from __future__ import annotations

import logging
import traceback
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from app.api.deps import authed_request
from app.core.config import Settings
from app.core.logging import log_with_extra
from app.schemas.base import BaseResponse, build_metadata
from app.schemas.market import (
    BulkOhlcvData,
    BulkOhlcvRequest,
    BulkSymbolError,
    SeriesSummary,
)
from app.services import yahoo

logger = logging.getLogger("app.api.bulk")

router = APIRouter(
    prefix="/bulk",
    tags=["market-data"],
    dependencies=[authed_request],
)


def _validated_symbols(settings: Settings, raw: list[str], interval: str) -> tuple[list[str], str]:
    if len(raw) > settings.bulk_max_symbols:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Bulk request too large",
                "details": [
                    f"symbols: {len(raw)} requested, limit is "
                    f"{settings.bulk_max_symbols} (BULK_MAX_SYMBOLS)"
                ],
            },
        )
    intraday = interval in yahoo.INTRADAY_INTERVALS
    intraday_cap = settings.bulk_intraday_symbols
    if intraday and len(raw) > intraday_cap:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Bulk request too large for intraday interval",
                "details": [
                    f"bulk: intraday interval {interval!r} allows at most "
                    f"{intraday_cap} symbols per call (BULK_INTRADAY_SYMBOLS), "
                    f"got {len(raw)}"
                ],
            },
        )
    issues: list[str] = []
    seen: set[str] = set()
    unique: list[str] = []
    for index, item in enumerate(raw):
        canonical = yahoo.validate_symbol(item)  # raises 422 with its own details
        if canonical in seen:
            issues.append(f"symbols[{index}]: duplicate {canonical}")
            continue
        seen.add(canonical)
        unique.append(canonical)
    for issue in issues:
        logger.info("bulk deduplicated: %s", issue)
    if not unique:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Bulk request needs at least one unique symbol",
                "details": issues or ["symbols: empty after deduplication"],
            },
        )
    return unique, ",".join(unique)


def _fetch_one(
    args: tuple[str, str, str | None, str | None, str | None, str | None, bool],
) -> tuple[str, SeriesSummary | None, BulkSymbolError | None]:
    symbol, interval, period, start, end, tz, adjust = args
    context = f"fetching {interval} OHLCV for {symbol}"
    try:
        df, meta = yahoo.fetch_ohlcv(symbol, interval, period, start, end, auto_adjust=adjust)
        if isinstance(df, pd.DataFrame) and df.empty:
            info, _ = yahoo.fetch_metadata(symbol)
            if not info:
                raise yahoo.YahooNotFound(
                    operation=context,
                    message=f"Yahoo Finance has no data for {symbol!r}",
                    raw="empty history + no info",
                    tb="",
                )
            log_with_extra(
                logger, logging.INFO, f"{context}: valid symbol, zero rows in window", symbol=symbol
            )
            frame = pd.DataFrame()
            meta = {}
        else:
            frame = df
        points, newest, oldest = yahoo.history_points(frame, interval, tz)
        summary = SeriesSummary(
            symbol=symbol,
            name=meta.get("shortName") or meta.get("longName") or None,
            quote_type=meta.get("instrumentType"),
            currency=meta.get("currency"),
            timezone=meta.get("timezone"),
            adjusted=adjust,
            newest=newest,
            oldest=oldest,
            observations=points,
        )
        return symbol, summary, None
    except yahoo.YahooError as exc:
        log_with_extra(logger, logging.ERROR, f"{context} failed", symbol=symbol, code=exc.code)
        return (
            symbol,
            None,
            BulkSymbolError(
                symbol=symbol,
                code=exc.code,
                message=f"{context}: {exc}",
                details=[
                    f"operation: {exc.operation}",
                    f"error: {exc.raw}",
                    "traceback:\n" + exc.traceback_text,
                ],
            ),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log_with_extra(
            logger, logging.ERROR, f"{context}: unexpected failure", symbol=symbol, error=repr(exc)
        )
        return (
            symbol,
            None,
            BulkSymbolError(
                symbol=symbol,
                code="upstream_unavailable",
                message=f"{context}: unexpected failure: {exc}",
                details=[
                    f"error: {type(exc).__name__}: {exc}",
                    "traceback:\n" + traceback.format_exc(),
                ],
            ),
        )


def _list_str(items: list[str]) -> str:
    return "; ".join(items[:10])


@router.post(
    "/ohlcv",
    summary="OHLCV for many symbols in one call (POST body, no pagination)",
    response_model=BaseResponse[BulkOhlcvData],
)
def bulk_ohlcv(request: Request, body: BulkOhlcvRequest) -> BaseResponse[BulkOhlcvData]:
    settings: Settings = request.app.state.settings
    symbols, _joined = _validated_symbols(settings, body.symbols, body.interval)
    if body.tz is not None:
        yahoo.validate_tz(body.tz)
    period, start, end, echoed_range = yahoo.resolve_ohlcv_params(
        body.interval, body.range, body.start_date, body.end_date
    )

    jobs = [(sym, body.interval, period, start, end, body.tz, body.adjust) for sym in symbols]
    max_workers = min(settings.yf_max_threads, len(jobs))
    log_with_extra(
        logger,
        logging.INFO,
        "bulk ohlcv start",
        symbols_len=len(jobs),
        interval=body.interval,
        workers=max_workers,
        range=echoed_range,
        start=start,
        end=end,
    )
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        outcomes = list(pool.map(_fetch_one, jobs))

    results: list[SeriesSummary] = []
    errors: list[BulkSymbolError] = []
    for _symbol, summary, error in outcomes:
        if summary is not None:
            results.append(summary)
        elif error is not None:
            errors.append(error)

    all_upstream_down = (
        bool(errors) and not results and all(e.code == "upstream_unavailable" for e in errors)
    )
    if all_upstream_down:
        log_with_extra(
            logger,
            logging.ERROR,
            "bulk ohlcv: every symbol failed upstream",
            symbols=len(symbols),
            first=_list_str([f"{e.symbol}: {e.message}" for e in errors]),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_unavailable",
                "message": (
                    f"bulk OHLCV failed for all {len(errors)} symbols: "
                    + _list_str([f"{e.symbol}" for e in errors])
                ),
                "details": [f"{e.symbol}: {e.message}" for e in errors],
            },
        )

    log_with_extra(
        logger,
        logging.INFO,
        "bulk ohlcv done",
        requested=len(symbols),
        succeeded=len(results),
        failed=len(errors),
    )
    data = BulkOhlcvData(
        interval=body.interval,
        range=echoed_range,
        requested=len(symbols),
        succeeded=len(results),
        failed=len(errors),
        results=results,
        errors=errors,
    )
    return BaseResponse[BulkOhlcvData](data=data, metadata=build_metadata(request))
