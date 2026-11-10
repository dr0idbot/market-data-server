"""Yahoo-boundary robustness: silent stubs, unreadable history_metadata."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import app.services.yahoo as ymodule
from app.services.yahoo import (
    _META_KEYSTONE,
    YahooNotFound,
    YahooUnavailable,
    fetch_metadata,
    fetch_ohlcv,
)


class _UnreadableMeta:
    """yfinance's error-side history_metadata: raises on item access."""

    def keys(self):
        return ("tradingPeriods",)

    def __iter__(self):
        return iter(("tradingPeriods",))

    def __getitem__(self, key):
        raise KeyError(key)


class _BrokenIsin:
    @property
    def isin(self):
        raise AttributeError("no isin")


class _Ticker:
    def __init__(self, df, meta, info, isin_ok: bool = True):
        self._df = df
        self._meta = meta
        self._info = info
        self._isin = _BrokenIsin() if not isin_ok else None

    def history(self, **kwargs):
        return self._df

    @property
    def history_metadata(self):
        return self._meta

    def get_info(self):
        return self._info

    @property
    def isin(self):
        if self._isin is not None:
            return self._isin
        return "US0000000000"


def test_ohlcv_unknown_symbol_meta_crash_maps_to_not_found(monkeypatch) -> None:
    """Regression: dict(history_metadata) used to raise KeyError -> HTTP 500."""
    monkeypatch.setattr(
        ymodule.yf, "Ticker", lambda sym: _Ticker(pd.DataFrame(), _UnreadableMeta(), {})
    )
    with pytest.raises(YahooNotFound):
        fetch_ohlcv("NOPE77", "1d", "1y", None, None)


def test_ohlcv_valid_empty_window_stays_valid(monkeypatch) -> None:
    meta = {"tradingPeriods": [], "instrumentType": "EQUITY"}
    monkeypatch.setattr(
        ymodule.yf, "Ticker", lambda sym: _Ticker(pd.DataFrame(), meta, {})
    )
    df, out_meta = fetch_ohlcv("AAPL", "1d", None, "2100-01-01", "2100-01-10")
    assert df.empty and out_meta == meta


def test_metadata_hollow_info_stub_maps_to_unavailable(monkeypatch) -> None:
    """Regression: {'trailingPegRatio': …}-only info must not fake a profile."""
    monkeypatch.setattr(
        ymodule.yf, "Ticker", lambda sym: _Ticker(pd.DataFrame(), {}, {"trailingPegRatio": 1.57})
    )
    with pytest.raises(YahooUnavailable):
        fetch_metadata("AAPL")


def test_metadata_keystones_make_profile_valid(monkeypatch) -> None:
    info = {"quoteType": "EQUITY", "shortName": "Apple", "currency": "USD"}
    monkeypatch.setattr(ymodule.yf, "Ticker", lambda sym: _Ticker(pd.DataFrame(), {}, info))
    got, _ = fetch_metadata("AAPL")
    assert got["shortName"] == "Apple"


def test_route_unknown_symbol_is_404_not_500(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get("/v1/ticker/GARBAGE1/ohlcv", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_meta_keystone_constant() -> None:
    assert _META_KEYSTONE == "tradingPeriods"
