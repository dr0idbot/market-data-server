"""Pydantic models for market data endpoints.

Response field naming and semantics follow the approved design:
misc/endpoints previews (docs were removed once implementation landed).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Shared with app.services.yahoo and tests; single source of truth.
ALLOWED_INTERVALS: tuple[str, ...] = (
    "1m",
    "2m",
    "5m",
    "15m",
    "30m",
    "90m",
    "1h",
    "1d",
    "5d",
    "1wk",
    "1mo",
    "3mo",
)
ALLOWED_RANGES: tuple[str, ...] = (
    "1d",
    "5d",
    "1mo",
    "3mo",
    "6mo",
    "1y",
    "2y",
    "5y",
    "10y",
    "ytd",
    "max",
)
DATE_GRANULAR_INTERVALS: frozenset[str] = frozenset({"1d", "5d", "1wk", "1mo", "3mo"})


class OhlcvPoint(BaseModel):
    time: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adj_close: float | None
    volume: int | None
    dividends: float
    splits: float


class SeriesSummary(BaseModel):
    """Fields shared by single-symbol OHLCV and per-symbol bulk results."""

    symbol: str
    name: str | None = None
    quote_type: str | None = None
    currency: str | None = None
    timezone: str | None = None
    adjusted: bool
    newest: str | None = None
    oldest: str | None = None
    observations: list[OhlcvPoint]


class OhlcvData(SeriesSummary):
    interval: str = "1d"
    range: str | None = None
    requested_start: str | None = None
    requested_end: str | None = None


class IdentityModel(BaseModel):
    symbol: str
    name: str | None = None
    long_name: str | None = None
    description: str | None = None
    website: str | None = None
    sector: str | None = None
    industry: str | None = None
    country: str | None = None
    city: str | None = None
    isin: str | None = None
    employees: int | None = None


class ClassificationModel(BaseModel):
    quote_type: str | None = None
    market: str | None = None
    exchange: str | None = None
    exchange_code: str | None = None
    exchange_timezone: str | None = None
    currency: str | None = None
    financial_currency: str | None = None


class TradingModel(BaseModel):
    last_price: float | None = None
    previous_close: float | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    avg_volume_3m: int | None = None
    avg_volume_10d: int | None = None
    bid: float | None = None
    bid_size: int | None = None
    ask: float | None = None
    ask_size: int | None = None
    fifty_two_week_low: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_change: float | None = None
    sp500_52w_change: float | None = None
    all_time_high: float | None = None
    all_time_low: float | None = None
    ma_50d: float | None = None
    ma_200d: float | None = None
    after_hours_price: float | None = None


class ValuationModel(BaseModel):
    market_cap: float | None = None
    book_value: float | None = None
    price_to_book: float | None = None
    pe_trailing: float | None = None
    pe_forward: float | None = None


class SharesModel(BaseModel):
    # populate_by_name: code constructs with the pythonic name (`float_`),
    # while JSON output keeps the alias key "float".
    model_config = ConfigDict(populate_by_name=True)

    outstanding: int | None = None
    float_: int | None = Field(default=None, alias="float")
    held_institutions: float | None = None
    held_insiders: float | None = None
    short_ratio: float | None = None
    short_percent_of_float: float | None = None
    short_interest_date: str | None = None


class EarningsModel(BaseModel):
    eps_trailing: float | None = None
    eps_forward: float | None = None
    next_earnings_start: str | None = None
    next_earnings_end: str | None = None
    is_earnings_date_estimate: bool | None = None


class DividendModel(BaseModel):
    dividend_rate: float | None = None
    dividend_yield: float | None = None
    five_year_avg_yield: float | None = None
    payout_ratio: float | None = None
    trailing_annual_rate: float | None = None
    trailing_annual_yield: float | None = None
    ex_dividend_date: str | None = None
    next_pay_date: str | None = None


class AnalystModel(BaseModel):
    target_mean: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_median: float | None = None
    recommendation: str | None = None
    recommendation_mean: float | None = None
    analyst_count: int | None = None


class MetadataData(BaseModel):
    identity: IdentityModel
    classification: ClassificationModel
    trading: TradingModel
    valuation: ValuationModel
    shares: SharesModel
    earnings: EarningsModel
    dividend: DividendModel
    analyst: AnalystModel
    raw: dict[str, Any] | None = None


class BulkSymbolError(BaseModel):
    symbol: str
    code: str
    message: str
    details: list[str] | None = None


class BulkOhlcvData(BaseModel):
    interval: str
    range: str | None = None
    requested: int
    succeeded: int
    failed: int
    results: list[SeriesSummary]
    errors: list[BulkSymbolError]


class BulkOhlcvRequest(BaseModel):
    symbols: list[str] = Field(min_length=1)
    interval: str = "1d"
    range: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    adjust: bool = True
    tz: str | None = None
