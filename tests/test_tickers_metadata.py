from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_metadata_requires_token(client: TestClient) -> None:
    resp = client.get("/v1/ticker/AAPL/metadata")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["data"] is None
    assert "request_id" in body["metadata"]


def test_metadata_rejects_wrong_token(client: TestClient) -> None:
    resp = client.get("/v1/ticker/AAPL/metadata", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_metadata_happy_path(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    resp = client.get("/v1/ticker/AAPL/metadata", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["error"] is None and body["pagination"] is None
    data = body["data"]
    identity = data["identity"]
    assert identity["symbol"] == "AAPL"
    assert identity["sector"] == "Technology"
    assert identity["industry"] == "Consumer Electronics"
    assert identity["isin"] == "US0378331005"
    classification = data["classification"]
    assert classification["quote_type"] == "EQUITY"
    assert classification["exchange_timezone"] == "America/New_York"
    trading = data["trading"]
    assert trading["last_price"] == 342.37
    assert trading["fifty_two_week_change"] == 0.0397
    assert data["dividend"]["dividend_yield"] == 0.0031
    assert data["analyst"]["target_mean"] == 294.38
    assert data["shares"]["held_institutions"] == 0.6687
    assert data["earnings"]["next_earnings_start"].endswith("Z")
    assert "request_id" in body["metadata"]
    assert resp.headers.get("X-Request-ID") == body["metadata"]["request_id"]


def test_metadata_extended_raw(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=["AAPL"])
    plain = client.get("/v1/ticker/AAPL/metadata", headers=auth_headers)
    assert plain.json()["data"].get("raw") is None

    extended = client.get("/v1/ticker/AAPL/metadata?extended=true", headers=auth_headers)
    raw_any: dict[str, Any] | None = extended.json()["data"]["raw"]
    assert raw_any is not None
    assert raw_any.get("quoteType") == "EQUITY"
    assert raw_any.get("companyOfficers")


def test_metadata_extended_raw_sanitizes_nan(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.yahoo as ymodule
    import tests.md_stubs as stubs

    broken = stubs.info_dict()
    broken["someFloat"] = float("nan")

    def fetch_meta(symbol: str):
        if symbol != "AAPL":
            raise ymodule.YahooNotFound(operation="get_info stub", message="no", raw="x")
        return broken, None

    monkeypatch.setattr(ymodule, "fetch_metadata", fetch_meta)
    resp = client.get("/v1/ticker/AAPL/metadata?extended=true", headers=auth_headers)
    assert resp.status_code == 200
    raw = resp.json()["data"]["raw"]
    assert raw["someFloat"] is None


def test_metadata_unknown_symbol_404(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[])
    resp = client.get("/v1/ticker/NOPE/metadata", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "NOPE" in body["error"]["message"]
    assert body["error"]["details"], "raw error context must not be omitted"
    assert any("operation:" in d for d in body["error"]["details"])


def test_metadata_invalid_symbol_charset(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/v1/ticker/AAP%20L/metadata", headers=auth_headers)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    details_text = " ".join(body["error"]["details"])
    assert "AAP L" in details_text or "unsupported characters" in details_text


def test_metadata_upstream_unavailable(
    client: TestClient, auth_headers: dict[str, str], yahoo_stub_factory
) -> None:
    yahoo_stub_factory(valid=[], fail={"AAPL": "unavailable"})
    resp = client.get("/v1/ticker/AAPL/metadata", headers=auth_headers)
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "upstream_unavailable"
    assert isinstance(body["error"]["details"], list)
