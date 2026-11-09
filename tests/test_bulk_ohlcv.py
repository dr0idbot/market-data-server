from __future__ import annotations

from fastapi.testclient import TestClient

URL = "/v1/bulk/ohlcv"


def test_bulk_requires_token(client: TestClient) -> None:
    resp = client.post(URL, json={"symbols": ["AAPL"]})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_bulk_get_not_allowed(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get(URL, headers=auth_headers)
    assert resp.status_code == 405


def test_bulk_happy_path_desc_order(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL", "BTC-USD", "7203.T"])
    resp = client.post(
        URL,
        headers=auth_headers,
        json={"symbols": ["AAPL", "BTC-USD", "7203.T"], "range": "5d"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None and body["pagination"] is None
    data = body["data"]
    assert data["requested"] == 3 and data["succeeded"] == 3 and data["failed"] == 0
    assert [r["symbol"] for r in data["results"]] == ["AAPL", "BTC-USD", "7203.T"]
    assert data["interval"] == "1d" and data["range"] == "5d"
    for result in data["results"]:
        times = [o["time"] for o in result["observations"]]
        assert times == sorted(times, reverse=True)
        assert result["adjusted"] is True
        assert result["quote_type"] == "EQUITY"


def test_bulk_partial_success_mixed(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL", "EURUSD=X"], fail={"NOPE": "ohlcv"})
    resp = client.post(
        URL,
        headers=auth_headers,
        json={"symbols": ["AAPL", "NOPE", "EURUSD=X"], "range": "1mo"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requested"] == 3
    assert data["succeeded"] == 2 and data["failed"] == 1
    assert [r["symbol"] for r in data["results"]] == ["AAPL", "EURUSD=X"]
    error = data["errors"][0]
    assert error["symbol"] == "NOPE"
    assert error["code"] == "not_found"
    assert error["details"], "raw upstream context must not be omitted"


def test_bulk_all_not_found_is_200(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[])
    resp = client.post(URL, headers=auth_headers, json={"symbols": ["NOPE", "ALSOX"]})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["succeeded"] == 0 and data["failed"] == 2
    assert data["results"] == []
    assert {e["code"] for e in data["errors"]} == {"not_found"}


def test_bulk_all_upstream_down_is_502(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[], fail={"AAPL": "unavailable", "MSFT": "unavailable"})
    resp = client.post(URL, headers=auth_headers, json={"symbols": ["AAPL", "MSFT"]})
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "upstream_unavailable"
    assert "AAPL" in body["error"]["message"] and "MSFT" in body["error"]["message"]
    assert len(body["error"]["details"]) == 2


def test_bulk_symbol_cap_enforced(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[])
    symbols = [f"S{i:03d}" for i in range(26)]  # over default cap 25
    resp = client.post(URL, headers=auth_headers, json={"symbols": symbols})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert "26" in body["error"]["message"] or "26" in " ".join(body["error"]["details"])


def test_bulk_empty_list_422(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.post(URL, headers=auth_headers, json={"symbols": []})
    assert resp.status_code == 422


def test_bulk_deduplicates_symbols(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.post(
        URL,
        headers=auth_headers,
        json={"symbols": ["AAPL", "aapl", " AAPL", "MSFT"], "range": "1d"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["requested"] == 2  # AAPL (deduped) + MSFT
    assert data["results"][0]["symbol"] == "AAPL"
    assert data["failed"] == 1 and data["errors"][0]["symbol"] == "MSFT"


def test_bulk_intraday_cap(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[])
    symbols = ["S001", "S002", "S003", "S004", "S005", "S006"]
    resp = client.post(URL, headers=auth_headers, json={"symbols": symbols, "interval": "1m"})
    assert resp.status_code == 422
    detail_text = " ".join(resp.json()["error"]["details"])
    assert "intraday" in detail_text or "bulk" in detail_text


def test_bulk_intraday_within_cap(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL", "MSFT", "GOOG"], intraday=True)
    resp = client.post(
        URL,
        headers=auth_headers,
        json={"symbols": ["AAPL", "MSFT", "GOOG"], "interval": "1m", "range": "5d"},
    )
    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    stamp = results[0]["observations"][0]["time"]
    assert "T" in stamp and "-05:00" in stamp


def test_bulk_shared_window_params(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL", "BTC-USD"])
    resp = client.post(
        URL,
        headers=auth_headers,
        json={"symbols": ["AAPL", "BTC-USD"], "start_date": "2026-10-01", "end_date": "2026-10-10"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["range"] is None
    assert data["results"][0]["newest"] is not None
