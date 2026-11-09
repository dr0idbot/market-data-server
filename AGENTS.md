# AGENTS.md — market-data-server

Guidance for AI agents (and humans) working in this repo.

## Project overview

Python REST API skeleton built with **FastAPI** + **pydantic**. No database.
Every endpoint is protected by a single shared token (`APP_TOKEN` env var) and
every request/response is logged/enveloped by the standards below.

## Commands

```bash
make install   # create .venv, install package + dev deps
make run       # run server (uvicorn) on :8000
make dev       # same with --reload
make test      # pytest
make lint      # ruff check + mypy
make fmt       # ruff format + autofix
make check     # lint + test
```

Always run `make check` after code changes and keep it green.

## Non-negotiable standards

### 1. Auth (APP_TOKEN)

- Every endpoint (whole `/v1` router tree) requires `Authorization: Bearer <APP_TOKEN>`.
  - The token is checked against the `APP_TOKEN` **env var**. See `app/core/auth.py`.
  - Comparison is constant-time. Wrong/missing token ⇒ `401` with base-schema body.
  - **Optional encrypted bearer** (`ENC-BEARER v1`): when `APP_TOKEN_ENC_KEY`
    env is set, `Bearer enc:<payload>` is ALSO accepted — payload =
    `std_base64( 12-byte nonce || AES-256-GCM(APP_TOKEN) )`, AES key =
    `SHA-256(UTF-8 of APP_TOKEN_ENC_KEY)`, AAD none. Unset env ⇒ `enc:` always
    401, plain still valid. Plain tokens starting with `enc:` are unsupported
    (reserved prefix). Reference impl + captured examples:
    `misc/references/01-authentication.md`, unit tests `tests/test_encrypted_auth.py`.
- New routers **must** declare `dependencies=[authed_request]` (see `app/api/deps.py`,
  used in `app/api/v1/health.py`). Never add an endpoint that skips bearer auth.
- Never log the token, the enc key, or include them in error messages.

### 2. Request logging (no exceptions)

- `RequestLoggingMiddleware` (`app/core/middleware.py`) logs **every** request
  (method, path, status, duration_ms, request_id, client). Do not mute it or add
  allow-lists for paths.
- Many log calls pass structured fields via `log_with_extra` — keep that helper
  when adding fields.

### 3. Response envelope

- **All** responses (success and error) use the base schema from
  `app/schemas/base.py`:

  ```json
  {
    "data": <payload or null>,
    "metadata": {"request_id", "timestamp", "service", "api_version", "duration_ms"},
    "pagination": {"total_items", "total_pages", "page", "page_size", "first_index", "has_next", "has_prev"} | null,
    "error": {"code", "message", "details"} | null
  }
  ```

- Success endpoints: return `BaseResponse(...)` with `build_metadata(request)`.
- Paginated list endpoints: accept `page: PageParamsQuery`, slice the item list,
  and set `pagination=build_pagination(params, total)`.
- Errors: raise `HTTPException` or let handlers do it — `app/api/errors.py`
  wraps **all** errors in the envelope (401/404/422/500 …). Never return a bare
  dict or raise a plain exception without going through these handlers.
- `X-Request-ID` is echoed back and present in `metadata.request_id`.

### 4. Config

- All configuration comes from env vars (see `.env.example`): `APP_TOKEN`,
  `APP_NAME`, `APP_ENV`, `LOG_LEVEL`, `LOG_JSON`. Access settings only via
  `get_settings()` (`app/core/config.py`).

## Conventions

- API versioning: all business routes live under `/v1` prefix; add new modules in
  `app/api/v1/` and register them in `app/api/v1/__init__.py`.
- Type hints everywhere; `mypy --strict` runs in `make lint`.
- Imports via absolute paths (`app.*`).
- Keep modules small and focused; no DB layer exists — if one is ever added,
  document it here and keep it behind repository interfaces.

## Market data endpoints (yfinance)

All Yahoo/yfinance access goes through `app/services/yahoo.py` (typed boundary:
fetchers, symbol/window validation, `YahooError` subclasses: `YahooNotFound`
→ 404 `not_found`, `YahooUnavailable` → 502 `upstream_unavailable`).

- `GET /v1/ticker/{symbol}/metadata` — full profile;
  `?extended=true` adds `raw` (whole yfinance info dict, NaN/inf sanitized).
- `GET /v1/ticker/{symbol}/ohlcv` — bars; `interval` + `range` OR
  `start_date`/`end_date` (both required, end date is INCLUSIVE);
  `adjust=false` returns raw close + Adj Close (calculations per bar);
  ALWAYS paginated, latest bar first (descending); default `page_size=252`
  (~1y of daily bars), clamped to `OHLCV_PAGE_SIZE_MAX`;
  `newest`/`oldest` describe the full window, not the page.
- `POST /v1/bulk/ohlcv` — one request per JSON body list of `symbols`
  (deduped, canonicalized); ordered per caller input; per-symbol failures land
  in `data.errors` (code/message/details incl. upstream raw + traceback);
  502 only when EVERY symbol failed upstream. No pagination on bulk.
  Caps: `BULK_MAX_SYMBOLS` (default 25); intraday intervals additionally
  cap at `BULK_INTRADAY_SYMBOLS` (default 5) to protect upstream.
- Symbol grammar (path + body): `^[A-Z0-9^._=\-+~]{1,15}$` after
  strip+uppercase; no `.`↔`-` rewriting; URL-encode specials (`^GSPC` →
  `%5EGSPC`, `EURUSD=X` → `EURUSD%3DX`).
- Intraday window caps: `1m` ≤ 8d, `2m/5m/15m/30m` ≤ 60d, `90m/1h` ≤ 730d;
  `range=max` is rejected for intraday intervals.
- Errors: upstream failures always log server-side (exception + context) and
  surface raw error text/traceback in the envelope `error.details`
  (dev-facing; no silent omission). Valid symbols with empty windows return
  200 with `observations: []`; unknown/delisted symbols are `not_found`.
- New env vars (see `.env.example`): `BULK_MAX_SYMBOLS`,
  `BULK_INTRADAY_SYMBOLS`, `YF_MAX_THREADS` (bulk worker pool),
  `OHLCV_PAGE_SIZE_MAX`.

## Testing

- Tests use `TestClient` + pytest (`tests/`). `APP_TOKEN` is preset to
  `test-token` in `tests/conftest.py` before app import.
- New endpoints need tests covering: auth 401, envelope shape (`data`/`metadata`),
  and pagination if list-based.

## Known trade-offs (skeleton)

- Single shared token = whoever holds it gets full access; rotate via env var.
- Request id is taken from the client `X-Request-ID` header if provided — trust
  boundary is the token.
- Docs (`/docs`, `/redoc`, `/openapi.json`) are disabled in `APP_ENV=prod`.
