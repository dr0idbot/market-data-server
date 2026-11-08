from fastapi.testclient import TestClient

BASE_SCHEMA_KEYS = {"data", "metadata"}


def test_health_requires_token(client: TestClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 401
    body = resp.json()
    assert BASE_SCHEMA_KEYS <= set(body)
    assert body["error"]["code"] == "unauthorized"
    assert "request_id" in body["metadata"]
    assert resp.headers.get("X-Request-ID") == body["metadata"]["request_id"]


def test_health_rejects_wrong_token(client: TestClient) -> None:
    resp = client.get("/v1/health", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["data"] is None
    assert body["error"]["code"] == "unauthorized"


def test_health_ok(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/v1/health", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert BASE_SCHEMA_KEYS <= set(body)
    assert body["pagination"] is None
    assert body["error"] is None
    assert body["data"] == {"status": "ok"}
    meta = body["metadata"]
    assert meta["service"] == "market-data-server"
    assert meta["api_version"]
    assert meta["timestamp"]
    assert resp.headers.get("X-Request-ID") == meta["request_id"]


def test_request_id_propagated(client: TestClient, auth_headers: dict[str, str]) -> None:
    resp = client.get("/v1/health", headers={**auth_headers, "X-Request-ID": "my-trace-1"})
    assert resp.headers.get("X-Request-ID") == "my-trace-1"
    assert resp.json()["metadata"]["request_id"] == "my-trace-1"


def test_unknown_route_follows_base_schema(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = client.get("/v1/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404
    body = resp.json()
    assert BASE_SCHEMA_KEYS <= set(body)
    assert body["error"]["code"] == "error"
    assert body["metadata"]["request_id"]
