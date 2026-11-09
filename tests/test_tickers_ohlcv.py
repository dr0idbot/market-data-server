from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

URL = "/v1/ticker/AAPL/ohlcv"


def test_ohlcv_requires_token(client: TestClient) -> None:
    resp = client.get(URL)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_ohlcv_rejects_wrong_token(client: TestClient) -> None:
    resp = client.get(URL, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_ohlcv_defaults_paginated_descending(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(URL, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None
    data = body["data"]
    assert data["symbol"] == "AAPL"
    assert data["interval"] == "1d"
    assert data["range"] == "1y"
    assert data["adjusted"] is True
    assert data["requested_start"] is None and data["requested_end"] is None
    obs = data["observations"]
    assert len(obs) == 252  # default page_size
    times = [o["time"] for o in obs]
    assert times == sorted(times, reverse=True)
    assert data["newest"] == times[0]
    # newest/oldest describe the whole window, not just this page
    assert data["oldest"] < times[-1]
    assert set(obs[0]) == {
        "time",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
        "dividends",
        "splits",
    }
    pagination = body["pagination"]
    assert pagination["total_items"] == 300
    assert pagination["total_pages"] == 2
    assert pagination["page"] == 1
    assert pagination["page_size"] == 252
    assert pagination["first_index"] == 0
    assert pagination["has_next"] is True
    assert pagination["has_prev"] is False


def test_ohlcv_page_two_slice(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(f"{URL}?page=2&page_size=100", headers=auth_headers)
    body = resp.json()
    pagination = body["pagination"]
    assert pagination["first_index"] == 100
    assert pagination["has_prev"] is True and pagination["has_next"] is True
    times = [o["time"] for o in body["data"]["observations"]]
    assert len(times) == 100
    assert times == sorted(times, reverse=True)
    first = client.get(f"{URL}?page=1&page_size=100", headers=auth_headers)
    page1_last = first.json()["data"]["observations"][-1]["time"]
    assert times[0] < page1_last


def test_ohlcv_last_page_smaller(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(f"{URL}?page=3&page_size=100", headers=auth_headers)
    body = resp.json()
    assert len(body["data"]["observations"]) == 100
    assert body["pagination"]["has_next"] is False

    partial = client.get(f"{URL}?page=3&page_size=125", headers=auth_headers)
    body = partial.json()
    assert len(body["data"]["observations"]) == 50
    assert body["pagination"]["first_index"] == 250


def test_ohlcv_page_size_clamped_by_env(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(f"{URL}?page_size=999999", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["pagination"]["page_size"] == 5000


def test_ohlcv_page_zero_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.get(f"{URL}?page=0", headers=auth_headers).status_code == 422


def test_ohlcv_adjust_false_returns_raw_and_adjclose(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(f"{URL}?range=5d&adjust=false", headers=auth_headers)
    data = resp.json()["data"]
    assert data["adjusted"] is False
    point = data["observations"][0]
    ratio = (point["adj_close"] - point["close"]) / point["close"]
    assert abs(ratio + 0.03) < 1e-6  # stub multiplies Close by 0.97 for Adj Close
    assert point["dividends"] == 0.25  # latest (desc-first) row carries the event


def test_ohlcv_adjust_true_adjclose_equals_close(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(f"{URL}?range=5d&adjust=true", headers=auth_headers)
    point = resp.json()["data"]["observations"][0]
    # yfinance auto_adjust=True has no separate Adj Close column: equal by design
    assert point["adj_close"] == point["close"]


def test_ohlcv_validation_matrix(client: TestClient, auth_headers: dict[str, str]) -> None:
    invalid = [
        f"{URL}?interval=4m",
        f"{URL}?interval=1m&range=1y",  # 366d > 8d cap
        f"{URL}?interval=1h&range=max",  # max disallowed intraday
        f"{URL}?range=awkward",
        f"{URL}?range=1y&start_date=2026-01-01",  # range XOR dates
        f"{URL}?start_date=2026-01-01",  # end missing
        f"{URL}?start_date=2026-02-01&end_date=2026-01-01",
        f"{URL}?interval=1m&start_date=2020-01-01&end_date=2026-01-01",
        f"{URL}?tz=Nowhere/Utopia",
    ]
    for url in invalid:
        resp = client.get(url, headers=auth_headers)
        assert resp.status_code == 422, url
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert body["error"]["details"]


def test_ohlcv_valid_intraday_window_allowed(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get(
        f"{URL}?interval=1h&start_date=2020-01-01&end_date=2021-01-01",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requested_start"] == "2020-01-01"
    assert data["range"] is None


def test_ohlcv_unknown_symbol_404(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get("/v1/ticker/NOPE/ohlcv", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "NOPE" in body["error"]["message"]
    assert body["error"]["details"]


def test_ohlcv_valid_symbol_empty_window_200(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory, monkeypatch
) -> None:
    import pandas as pd

    import app.services.yahoo as ymodule
    import tests.md_stubs as stubs

    yahoo_stub_factory(valid=["AAPL"])

    def empty_fetch(symbol, interval, period, start, end, auto_adjust=True):
        if symbol != "AAPL":
            raise ymodule.YahooNotFound(operation="history stub", message="no data", raw="missing")
        return pd.DataFrame(), stubs.history_meta()

    monkeypatch.setattr(ymodule, "fetch_ohlcv", empty_fetch)
    resp = client.get(f"{URL}?start_date=2100-01-01&end_date=2100-01-10", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["newest"] is None and data["oldest"] is None
    assert data["observations"] == []
    pagination = resp.json()["pagination"]
    assert pagination["total_items"] == 0
    assert pagination["has_next"] is False and pagination["has_prev"] is False


def test_ohlcv_intraday_tz_labelling(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"], intraday=True)
    resp = client.get(f"{URL}?interval=1m&range=5d", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["timezone"] == "America/New_York"
    stamp = data["observations"][0]["time"]
    assert "T" in stamp and "-05:00" in stamp


def test_ohlcv_upstream_unavailable_502(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[], fail={"AAPL": "unavailable"})
    resp = client.get(URL, headers=auth_headers)
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "upstream_unavailable"
    assert any(
        "connection" in d or "throttled" in d or "too many" in d for d in body["error"]["details"]
    ), "raw upstream error text must be visible"


def test_ohlcv_errors_logged_server_side(
    client: TestClient,
    auth_headers: dict[str, str],
    yahoo_stub_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    yahoo_stub_factory(valid=[], fail={"AAPL": "unavailable"})
    with caplog.at_level("ERROR"):
        client.get(URL, headers=auth_headers)
    messages = [str(record.msg) for record in caplog.records]
    assert any("failed" in msg and "AAPL" in msg for msg in messages)
