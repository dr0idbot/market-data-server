"""Typed yfinance access layer for the market-data endpoints.

Boundary rules:
- Every yfinance call happens here and only here.
- Upstream failures raise YahooError subclasses carrying the operation
  context, raw error text and traceback; they are always logged server-side
  and surfaced to the caller (dev-facing, no silent omission).
- Low-level symbol/window validation raises HTTPException(422) with
  per-parameter detail strings.
"""

from __future__ import annotations

import logging
import math
import re
import traceback
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from fastapi import HTTPException

from app.schemas.market import (
    ALLOWED_INTERVALS,
    ALLOWED_RANGES,
    DATE_GRANULAR_INTERVALS,
    AnalystModel,
    ClassificationModel,
    DividendModel,
    EarningsModel,
    IdentityModel,
    MetadataData,
    OhlcvPoint,
    SharesModel,
    TradingModel,
    ValuationModel,
)

logger = logging.getLogger("app.services.yahoo")

SYMBOL_RE = re.compile(r"^[A-Z0-9^._=\-+~]{1,15}$")

# Approximate period lengths (calendar days) for intraday window-cap checks.
PERIOD_APPROX_DAYS: dict[str, int] = {
    "1d": 1,
    "5d": 5,
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
    "5y": 1826,
    "10y": 3660,
}

INTERVAL_MAX_DAYS: dict[str, int] = {
    "1m": 8,
    "2m": 60,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "90m": 730,
    "1h": 730,
}

INTRADAY_INTERVALS: frozenset[str] = frozenset(INTERVAL_MAX_DAYS)

DEFAULT_RANGE = "1y"


# Keys that separate "Yahoo served a real profile" from its silent
# repair-fallback stub (e.g. {"trailingPegRatio": …}) seen on datacenter IPs.
_INFO_KEYSTONES: tuple[str, ...] = (
    "quoteType", "shortName", "longName", "sector", "marketCap", "currency",
    "displayName", "firstTradeDate", "regularMarketPrice",
)

# history_meta marker present for every readable/upstream-healthy history call.
_META_KEYSTONE = "tradingPeriods"


class YahooError(Exception):
    code = "upstream_unavailable"

    def __init__(self, operation: str, message: str, raw: str, tb: str) -> None:
        super().__init__(message)
        self.operation = operation
        self.raw = raw
        self.traceback_text = tb
        self.http_status = 502

    def details(self) -> list[str]:
        return [
            f"operation: {self.operation}",
            f"rawerror: {self.raw}",
            "traceback:\n" + self.traceback_text,
        ]


class YahooNotFound(YahooError):
    code = "not_found"

    def __init__(self, operation: str, message: str, raw: str, tb: str = "") -> None:
        super().__init__(operation, message, raw, tb)
        self.http_status = 404


class YahooUnavailable(YahooError):
    """Upstream throttled, timed out or otherwise unreachable (502)."""

    def __init__(self, operation: str, message: str, raw: str, tb: str = "") -> None:
        super().__init__(operation, message, raw, tb)


def _wrap(fn_name: str, symbol: str, exc: Exception) -> YahooError:
    """Classify a yfinance exception. Always logs server-side."""
    raw = f"{type(exc).__name__}: {exc}"
    lower = raw.lower()
    not_found = (
        "not found",
        "no fundamentals",
        "no timezone",
        "delisted",
        "prices missing",
        "symbol may be",
    )
    throttle = ("429", "too many requests", "rate limit", "connection", "timeout", "temporarily")
    if any(k in lower for k in not_found):
        cls: type[YahooError] = YahooNotFound
    elif any(k in lower for k in throttle):
        cls = YahooUnavailable
    else:
        cls = YahooUnavailable
    err = cls(
        f"yfinance {fn_name} for {symbol!r}",
        str(exc) or type(exc).__name__,
        raw,
        traceback.format_exc(),
    )
    logger.exception("Yahoo fetch failed: %s(%s) -> %s", fn_name, symbol, cls.__name__)
    return err


def validate_symbol(source: str) -> str:
    """Path/query symbol -> validated, canonical (uppercase, trimmed) symbol."""
    canonical = source.strip().upper()
    if not SYMBOL_RE.match(canonical):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Invalid ticker symbol",
                "details": [
                    f"symbol: {source!r} is invalid - must match "
                    "^[A-Z0-9^._=\\-+~]{1,15}$ after stripping/uppercasing"
                ],
            },
        )
    return canonical


def validate_tz(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Invalid timezone",
                "details": [f"tz: {tz!r} is not a valid IANA timezone"],
            },
        ) from None


def _parse_ymd(kind: str, value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Invalid date parameter",
                "details": [f"{kind}: {value!r} - expected ISO date YYYY-MM-DD"],
            },
        ) from None


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def _num_raw(value: Any) -> float | None:
    """Yahoo sometimes nests numbers in {'raw': x} dicts (summaryDetail)."""
    if isinstance(value, dict):
        return _num(value.get("raw"))
    return _num(value)


def _int_num(value: object) -> int | None:
    number = _num(value)
    return None if number is None else int(round(number))


def _date_str(epoch: Any) -> str | None:
    if not isinstance(epoch, (int, float)) or epoch <= 0:
        return None
    return datetime.fromtimestamp(float(epoch), tz=UTC).date().isoformat()


def _iso_str(epoch: Any) -> str | None:
    if not isinstance(epoch, (int, float)) or epoch <= 0:
        return None
    stamp = datetime.fromtimestamp(float(epoch), tz=UTC)
    return stamp.isoformat().replace("+00:00", "Z")


def _first(info: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = info.get(key)
        if value is not None:
            return value
    return None


def resolve_ohlcv_params(
    interval: str,
    range_: str | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Validate OHLCV window arguments.

    Returns (period, start, end, range_to_echo). Windowing is mutually
    exclusive: explicit start/end together with a `range` is an error.
    When neither dates nor range are given, the range defaults to '1y'.
    """
    issues: list[str] = []
    if interval not in ALLOWED_INTERVALS:
        issues.append(f"interval: {interval!r} not one of {','.join(ALLOWED_INTERVALS)}")
    if range_ is not None and range_ not in ALLOWED_RANGES:
        issues.append(f"range: {range_!r} not one of {','.join(ALLOWED_RANGES)}")
    has_start, has_end = start_date is not None, end_date is not None
    if has_start != has_end:
        issues.append("start_date/end_date: both must be provided together")
    if has_start and has_end and range_ is not None:
        issues.append("range: must be omitted when start_date/end_date are given")
    if issues:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "message": "Invalid OHLCV query",
                "details": issues,
            },
        )

    if start_date is not None and end_date is not None:  # both-or-neither enforced above
        d0, d1 = _parse_ymd("start_date", start_date), _parse_ymd("end_date", end_date)
        more: list[str] = []
        if d0 > d1:
            more.append(f"start_date: {d0} must be <= end_date {d1}")
        cap = INTERVAL_MAX_DAYS.get(interval)
        span_days = (d1 - d0).days + 1
        if cap is not None and span_days > cap:
            more.append(
                f"window: {span_days} days exceeds the {cap}-day limit for interval {interval!r}"
            )
        if more:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_error",
                    "message": "Invalid OHLCV window",
                    "details": more,
                },
            )
        return None, d0.isoformat(), d1.isoformat(), None

    effective_range = range_ or DEFAULT_RANGE
    if interval in INTRADAY_INTERVALS:
        cap = INTERVAL_MAX_DAYS[interval]
        if effective_range == "max":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_error",
                    "message": "Invalid OHLCV window",
                    "details": [f"range: 'max' is not allowed for intraday interval {interval!r}"],
                },
            )
        today = date.today()
        span = (
            (today - today.replace(month=1, day=1)).days + 1
            if effective_range == "ytd"
            else PERIOD_APPROX_DAYS[effective_range]
        )
        if span > cap:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation_error",
                    "message": "Invalid OHLCV window",
                    "details": [
                        f"range: {effective_range} (~{span} days) exceeds the "
                        f"{cap}-day limit for interval {interval!r}"
                    ],
                },
            )
    return effective_range, None, None, effective_range


def fetch_metadata(symbol: str) -> tuple[dict[str, Any], str | None]:
    """Fetch the full info dict + canonical ISIN; raises YahooError on failure.

    Yahoo sometimes answers with a silent, near-empty info stub instead of
    erroring (seen from datacenter IPs). That is reported as
    YahooUnavailable — we refuse to hand callers a hollow profile.
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.get_info() or {}
        if not enough_profile_keys(info):
            raise YahooUnavailable(
                operation=f"yfinance get_info for {symbol!r}",
                message=(
                    f"Yahoo returned no usable profile for {symbol!r}: symbol may "
                    "be unknown/delisted, or Yahoo is not serving profile data for "
                    "this caller (IP throttling). Retry later or from another host."
                ),
                raw=f"info keys received: {sorted(info)[:8]}",
                tb="",
            )
    except YahooError:
        raise
    except Exception as exc:
        raise _wrap("get_info", symbol, exc) from exc
    try:
        raw_isin: str | None = ticker.isin or None
    except Exception as exc:
        logger.warning("isin lookup skipped for %s: %s", symbol, exc)
        raw_isin = None
    return info, raw_isin


def build_metadata_data(info: dict[str, Any], symbol: str, isin: str | None) -> MetadataData:
    """Map the raw Yahoo info dict onto the approved response schema."""
    return MetadataData(
        identity=IdentityModel(
            symbol=symbol,
            name=_first(info, "shortName", "displayName", "longName"),
            long_name=info.get("longName"),
            description=info.get("longBusinessSummary"),
            website=info.get("website"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            country=info.get("country"),
            city=info.get("city"),
            isin=isin,
            employees=_int_num(info.get("fullTimeEmployees")),
        ),
        classification=ClassificationModel(
            quote_type=info.get("quoteType"),
            market=info.get("market"),
            exchange=info.get("fullExchangeName"),
            exchange_code=info.get("exchange"),
            exchange_timezone=info.get("exchangeTimezoneName"),
            currency=info.get("currency"),
            financial_currency=info.get("financialCurrency"),
        ),
        trading=TradingModel(
            last_price=_num_raw(_first(info, "currentPrice", "regularMarketPrice")),
            previous_close=_num_raw(_first(info, "regularMarketPreviousClose", "previousClose")),
            day_open=_num_raw(_first(info, "open", "regularMarketOpen")),
            day_high=_num_raw(_first(info, "dayHigh", "regularMarketDayHigh")),
            day_low=_num_raw(_first(info, "dayLow", "regularMarketDayLow")),
            volume=_int_num(_first(info, "regularMarketVolume", "volume")),
            avg_volume_3m=_int_num(_first(info, "averageDailyVolume3Month", "averageVolume")),
            avg_volume_10d=_int_num(_first(info, "averageDailyVolume10Day", "averageVolume10days")),
            bid=_num_raw(info.get("bid")),
            bid_size=info.get("bidSize"),
            ask=_num_raw(info.get("ask")),
            ask_size=info.get("askSize"),
            fifty_two_week_low=_num_raw(info.get("fiftyTwoWeekLow")),
            fifty_two_week_high=_num_raw(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_change=_num_raw(info.get("52WeekChange")),
            sp500_52w_change=_num_raw(info.get("SandP52WeekChange")),
            all_time_high=_num_raw(info.get("allTimeHigh")),
            all_time_low=_num_raw(info.get("allTimeLow")),
            ma_50d=_num_raw(info.get("fiftyDayAverage")),
            ma_200d=_num_raw(info.get("twoHundredDayAverage")),
            after_hours_price=_num_raw(_first(info, "postMarketPrice", "preMarketPrice")),
        ),
        valuation=ValuationModel(
            market_cap=_num_raw(info.get("marketCap")),
            book_value=_num_raw(info.get("bookValue")),
            price_to_book=_num_raw(info.get("priceToBook")),
            pe_trailing=_num_raw(info.get("trailingPE")),
            pe_forward=_num_raw(info.get("forwardPE")),
        ),
        shares=SharesModel(
            outstanding=info.get("sharesOutstanding"),
            float=info.get("floatShares"),
            held_institutions=_num_raw(info.get("heldPercentInstitutions")),
            held_insiders=_num_raw(info.get("heldPercentInsiders")),
            short_ratio=_num_raw(info.get("shortRatio")),
            short_percent_of_float=_num_raw(info.get("shortPercentOfFloat")),
            short_interest_date=_date_str(info.get("dateShortInterest")),
        ),
        earnings=EarningsModel(
            eps_trailing=_num_raw(info.get("trailingEps")),
            eps_forward=_num_raw(info.get("forwardEps")),
            next_earnings_start=_iso_str(info.get("earningsTimestampStart")),
            next_earnings_end=_iso_str(info.get("earningsTimestampEnd")),
            is_earnings_date_estimate=info.get("isEarningsDateEstimate"),
        ),
        dividend=DividendModel(
            dividend_rate=_num_raw(info.get("dividendRate")),
            dividend_yield=_num_raw(info.get("dividendYield")),
            five_year_avg_yield=_num_raw(info.get("fiveYearAvgDividendYield")),
            payout_ratio=_num_raw(info.get("payoutRatio")),
            trailing_annual_rate=_num_raw(info.get("trailingAnnualDividendRate")),
            trailing_annual_yield=_num_raw(info.get("trailingAnnualDividendYield")),
            ex_dividend_date=_date_str(info.get("exDividendDate")),
            next_pay_date=_date_str(info.get("dividendDate")),
        ),
        analyst=AnalystModel(
            target_mean=_num_raw(info.get("targetMeanPrice")),
            target_high=_num_raw(info.get("targetHighPrice")),
            target_low=_num_raw(info.get("targetLowPrice")),
            target_median=_num_raw(info.get("targetMedianPrice")),
            recommendation=info.get("recommendationKey"),
            recommendation_mean=_num_raw(info.get("recommendationMean")),
            analyst_count=info.get("numberOfAnalystOpinions"),
        ),
    )


def fetch_ohlcv(
    symbol: str,
    interval: str,
    period: str | None,
    start: str | None,
    end: str | None,
    auto_adjust: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch price history; returns the raw ascending DataFrame + chart meta.

    `end` is treated as INCLUSIVE (API contract). yfinance's history() end
    argument is exclusive, so we shift it forward one day upstream and trim
    the frame back to the requested calendar day afterwards.
    """
    kwargs: dict[str, Any] = {"auto_adjust": auto_adjust, "actions": True}
    trim_date: date | None = None
    if period is not None:
        kwargs["period"] = period
    if start is not None and end is not None:
        trim_date = _parse_ymd("end", end)
        kwargs["start"] = start
        kwargs["end"] = (trim_date + timedelta(days=1)).isoformat()
    try:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(interval=interval, **kwargs)
    except YahooError:
        raise
    except Exception as exc:
        raise _wrap("history", symbol, exc) from exc
    df = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    if trim_date is not None and not df.empty:
        df = _trim_bars_after(df, trim_date)
    meta = _history_meta_dict(ticker, symbol)
    if df.empty and _META_KEYSTONE not in meta:
        raise YahooNotFound(
            operation=f"yfinance history for {symbol!r}",
            message=(
                f"Yahoo returned no bars for {symbol!r}: symbol is unknown or "
                "delisted, or the requested window is empty"
            ),
            raw=f"history_metadata missing {_META_KEYSTONE!r}",
            tb="",
        )
    return df, meta


def _history_meta_dict(ticker: Any, symbol: str) -> dict[str, Any]:
    """dict() around yfinance's history_metadata; its __getitem__ may KeyError."""
    obj = getattr(ticker, "history_metadata", None)
    if not obj:
        return {}
    try:
        return dict(obj)
    except Exception as exc:
        logger.warning("history_metadata unreadable for %s: %s: %s", symbol,
                       type(exc).__name__, exc)
        return {}


def enough_profile_keys(info: dict[str, Any]) -> bool:
    """True when info carries at least one keystone of a genuine profile."""
    return any(key in info for key in _INFO_KEYSTONES)


def _trim_bars_after(df: pd.DataFrame, end_date: date) -> pd.DataFrame:
    """Drop bars whose exchange-local calendar date is later than end_date."""
    if isinstance(df.index, pd.DatetimeIndex):
        keep = [stamp.date() <= end_date for stamp in df.index]
        return df.iloc[[i for i, ok in enumerate(keep) if ok]]
    return df


def history_points(
    df: pd.DataFrame,
    interval: str,
    tz: str | None,
) -> tuple[list[OhlcvPoint], str | None, str | None]:
    """DataFrame -> descending observations (latest bar first)."""
    if df.empty:
        return [], None, None
    if tz is not None:
        validate_tz(tz)
    daily = interval in DATE_GRANULAR_INTERVALS

    def fmt(ts: pd.Timestamp) -> str:
        if daily:
            return ts.strftime("%Y-%m-%d")
        if ts.tzinfo is not None and tz is not None:
            return ts.tz_convert(ZoneInfo(tz)).isoformat()
        return ts.isoformat()

    points = [
        OhlcvPoint(
            time=fmt(pd.Timestamp(str(index) if index is not None else "")),
            open=_num(row.get("Open")),
            high=_num(row.get("High")),
            low=_num(row.get("Low")),
            close=_num(row.get("Close")),
            adj_close=(_num(row["Adj Close"]) if "Adj Close" in row else _num(row.get("Close"))),
            volume=_int_num(row.get("Volume")),
            dividends=_num(row.get("Dividends")) or 0.0,
            splits=_num(row.get("Stock Splits")) or 0.0,
        )
        for index, row in df.iloc[::-1].iterrows()
    ]
    newest = points[0].time if points else None
    oldest = points[-1].time if points else None
    return points, newest, oldest


def sanitize_json(obj: Any, _depth: int = 0) -> Any:
    """Normalize an upstream payload for strict JSON: NaN/inf -> None."""
    if _depth > 12:
        return str(obj)
    if obj is None or isinstance(obj, bool | int | str):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [sanitize_json(v, _depth + 1) for v in obj]
    number = _num(obj)
    return number if number is not None else str(obj)
