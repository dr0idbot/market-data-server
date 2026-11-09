"""Unit tests for the Yahoo symbol validator (no network)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from fastapi import HTTPException

from app.services.yahoo import (
    SYMBOL_RE,
    _trim_bars_after,
    resolve_ohlcv_params,
    validate_symbol,
)


def _frame(stamps: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {"Close": [10.0 + i for i in range(len(stamps))]}, index=stamps
    )


def test_trim_bars_after_naive_index_inclusive() -> None:
    idx = pd.DatetimeIndex(
        ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
    )
    trimmed = _trim_bars_after(_frame(idx), date(2026, 10, 6))
    assert list(trimmed.index) == list(idx[:4])  # Oct 6 included, Oct 7 dropped


def test_trim_bars_after_tz_index_inclusive() -> None:
    idx = pd.bdate_range("2026-10-01", "2026-10-07", tz="America/New_York")
    trimmed = _trim_bars_after(_frame(idx), date(2026, 10, 6))
    assert list(trimmed.index) == list(idx[:4])


def test_trim_bars_after_intraday_next_day_dropped() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-10-06 15:59:00",
            "2026-10-06 16:30:00",
            "2026-10-07 09:30:00",
        ]
    )
    trimmed = _trim_bars_after(_frame(idx), date(2026, 10, 6))
    assert list(trimmed.index) == list(idx[:2])


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("AAPL", "AAPL"),
        ("aapl", "AAPL"),
        (" BRK-B ", "BRK-B"),
        ("7203.t", "7203.T"),
        ("0700.hk", "0700.HK"),
        ("^gspc", "^GSPC"),
        ("eurusd=x", "EURUSD=X"),
        ("btc-usd", "BTC-USD"),
        ("es=f", "ES=F"),
        ("bp.l", "BP.L"),
    ],
)
def test_validate_symbol_accepts_yahoo_grammar(raw: str, expected: str) -> None:
    assert validate_symbol(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "                 ",
        "AAPL/MSFT",
        "AAP L",
        "NO%PE",
        "SYMBOL&CO",
        "SOME/*PATH",
        "UNI\u00e9",
        "A" * 16,
    ],
)
def test_validate_symbol_rejects_junk(raw: str) -> None:
    with pytest.raises(HTTPException) as ctx:
        validate_symbol(raw)
    assert ctx.value.status_code == 422
    assert ctx.value.detail["code"] == "validation_error"


def test_validate_symbol_length_cap_15() -> None:
    assert SYMBOL_RE.match("A" * 15)
    assert not SYMBOL_RE.match("A" * 16)


@pytest.mark.parametrize(
    "interval,range_,start,end,expect",
    [
        ("1d", "1y", None, None, ("1y", None, None, "1y")),
        ("1d", None, None, None, ("1y", None, None, "1y")),  # default range
        ("1m", "5d", None, None, ("5d", None, None, "5d")),
        ("1h", None, "2020-01-01", "2021-01-01", (None, "2020-01-01", "2021-01-01", None)),
    ],
)
def test_resolve_params_ok(
    interval: str,
    range_: str | None,
    start: str | None,
    end: str | None,
    expect: tuple,
) -> None:
    assert resolve_ohlcv_params(interval, range_, start, end) == expect


@pytest.mark.parametrize(
    "interval,range_,start,end",
    [
        ("4m", None, None, None),  # invalid interval
        ("1d", "awkward", None, None),  # invalid range
        ("1m", "1y", None, None),  # intraday window cap
        ("1h", "max", None, None),  # max + intraday
        ("1d", "1y", "2026-01-01", None),  # range XOR dates
        ("1d", "1y", None, "2026-02-01"),  # one-sided dates
        ("1d", "1y", "2026-01-01", "2026-02-01"),  # both+d range
        ("1d", None, "2026-02-01", "2026-01-01"),  # start > end
    ],
)
def test_resolve_params_rejects(
    interval: str,
    range_: str | None,
    start: str | None,
    end: str | None,
) -> None:
    with pytest.raises(HTTPException) as ctx:
        resolve_ohlcv_params(interval, range_, start, end)
    assert ctx.value.status_code == 422
    assert ctx.value.detail["code"] == "validation_error"
    assert ctx.value.detail["details"]
