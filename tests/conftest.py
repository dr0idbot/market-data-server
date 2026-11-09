"""Test fixtures. Token tests use APP_TOKEN=test-token via conftest env."""

import os

import pytest

# Must be set before app.settings is first imported/cached.
os.environ.setdefault("APP_TOKEN", "test-token")
os.environ.setdefault("APP_ENV", "dev")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, headers=None)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def yahoo_stub_factory(monkeypatch: pytest.MonkeyPatch):
    """Patch app.services.yahoo fetchers with canned, network-free data.

    factory(valid=[...], fail={SYMBOL: "meta"|"ohlcv"|"unavailable"}, intraday=False)
    - valid symbols return md_stubs fixtures; others raise YahooNotFound.
    - fail['unavailable']-style mode forces YahooUnavailable for that symbol.
    """

    def factory(
        valid: list[str],
        fail: dict[str, str] | None = None,
        intraday: bool = False,
    ):
        import tests.md_stubs as stubs
        from app.services import yahoo as ymodule

        fmap = {k.upper(): v for k, v in (fail or {}).items()}
        valid_set = {s.upper() for s in valid}

        def fetch_metadata(symbol: str) -> tuple[dict, str | None]:
            if fmap.get(symbol) == "unavailable":
                raise ymodule.YahooUnavailable(
                    operation=f"get_info stub for {symbol}",
                    message="Yahoo throttled connection",
                    raw="ConnectionResetError: too many requests",
                )
            if symbol in valid_set:
                return stubs.info_dict(), "US0378331005" if symbol == "AAPL" else None
            raise ymodule.YahooNotFound(
                operation="get_info stub",
                message="Yahoo Finance has no details for this symbol",
                raw="stub: not found",
            )

        def fetch_ohlcv(
            symbol: str,
            interval: str,
            period: str | None,
            start: str | None,
            end: str | None,
            auto_adjust: bool = True,
        ):
            want_fail = fmap.get(symbol)
            if want_fail == "unavailable":
                raise ymodule.YahooUnavailable(
                    operation=f"history stub for {symbol}",
                    message="Yahoo throttled connection",
                    raw="ConnectionResetError: too many requests",
                )
            if symbol in valid_set:
                df = (
                    stubs.intraday_df(adjusted=not auto_adjust)
                    if intraday
                    else stubs.daily_df(days=300, adjusted=not auto_adjust)
                )
                return df, stubs.history_meta()
            raise ymodule.YahooNotFound(
                operation=f"history stub for {symbol}",
                message="Yahoo Finance has no data for this symbol",
                raw="YFPricesMissingError: possibly delisted; no timezone found",
            )

        monkeypatch.setattr(ymodule, "fetch_metadata", fetch_metadata)
        monkeypatch.setattr(ymodule, "fetch_ohlcv", fetch_ohlcv)

    return factory
