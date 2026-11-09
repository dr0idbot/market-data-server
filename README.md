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

| Method | Path                          | Auth   | Description                                    |
| ------ | ----------------------------- | ------ | ---------------------------------------------- |
| GET    | `/v1/health`                  | Bearer | Liveness/readiness check                       |
| GET    | `/v1/ticker/{symbol}/metadata`| Bearer | Company profile; `?extended=true` adds `raw`   |
| GET    | `/v1/ticker/{symbol}/ohlcv`   | Bearer | Bars; interval/range or start/end; paginated   |
| POST   | `/v1/bulk/ohlcv`              | Bearer | Many symbols in one call (POST body)           |
| GET    | `/docs`                       | —      | OpenAPI UI (non-prod only)                     |

### Auth

Send the shared token on every call — plain, or (optionally) encrypted:

```bash
curl -H "Authorization: Bearer $APP_TOKEN" http://localhost:8000/v1/health
```

When the server sets `APP_TOKEN_ENC_KEY`, clients may instead send an
encrypted bearer: `Authorization: Bearer enc:<payload>` (ENC-BEARER v1:
`base64(nonce12 || AES-256-GCM(APP_TOKEN))`, AES key = `SHA-256(UTF-8 of
APP_TOKEN_ENC_KEY)`). Plain bearers stay valid in both modes. Full spec + a
Java reference implementation: `misc/references/01-authentication.md`.

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
  schemas/market.py  # market-data request/response models
  services/yahoo.py  # typed yfinance boundary (fetchers, validation, errors)
  api/
    deps.py          # shared dependencies (authed_request)
    errors.py        # envelope-wrapped exception handlers
    v1/health.py     # /v1/health
    v1/tickers.py    # /v1/ticker/{symbol}/metadata, /ohlcv
    v1/bulk.py       # POST /v1/bulk/ohlcv
tests/               # pytest + TestClient
```

## Development

```bash
make check   # ruff + mypy + pytest
```

See `AGENTS.md` for the standards/conventions agents must follow when
extending this service.
