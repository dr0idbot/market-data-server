# market-data-server

Python REST API skeleton (FastAPI). No database; JWT-free auth using a single
shared `APP_TOKEN` bearer token; every request logged; every response wrapped
in a base schema with request metadata and pagination support.

## Quickstart

```bash
make install
export APP_TOKEN="<your-secret>"
make run          # http://0.0.0.0:8000
```

Dev mode with auto-reload: `make dev`. Copy `.env.example` to `.env` to
configure (or export the vars directly).

## Endpoints

| Method | Path        | Auth  | Description                  |
| ------ | ----------- | ----- | ---------------------------- |
| GET    | `/v1/health`| Bearer| Liveness/readiness check     |
| GET    | `/docs`     | —     | OpenAPI UI (non-prod only)   |

### Auth

Send the shared token on every call:

```bash
curl -H "Authorization: Bearer $APP_TOKEN" http://localhost:8000/v1/health
```

### Response envelope

Every response (success and error) follows:

```json
{
  "data": {"status": "ok"},
  "metadata": {
    "request_id": "…",
    "timestamp": "2026-11-08T12:00:00Z",
    "service": "market-data-server",
    "api_version": "1.0.0",
    "duration_ms": 0.42
  },
  "pagination": null,
  "error": null
}
```

List endpoints additionally set `pagination` (add `?page=1&page_size=25` once
such endpoints exist — `PageParamsQuery` is ready to use). Errors include a
`{"code", "message", "details"}` `error` object instead of `data`.
`X-Request-ID` echoes a caller-supplied id or a generated one.

## Project layout

```
app/
  main.py            # app factory, lifespan, router wiring
  core/
    config.py        # env-based settings (pydantic-settings)
    auth.py          # APP_TOKEN bearer dependency
    middleware.py    # request logging + X-Request-ID
    logging.py       # logging setup (plain or JSON)
  schemas/base.py    # base response envelope, pagination, errors
  api/
    deps.py          # shared dependencies (authed_request)
    errors.py        # envelope-wrapped exception handlers
    v1/health.py     # /v1/health
tests/               # pytest + TestClient
```

## Development

```bash
make check   # ruff + mypy + pytest
```

See `AGENTS.md` for the standards/conventions agents must follow when
extending this service.
