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
- New routers **must** declare `dependencies=[authed_request]` (see `app/api/deps.py`,
  used in `app/api/v1/health.py`). Never add an endpoint that skips bearer auth.
- Never log the token or include it in error messages.

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
