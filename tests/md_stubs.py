"""Canned fixtures for network-free market-data tests."""

from __future__ import annotations

from typing import Any

import pandas as pd

AUTH = {"Authorization": "Bearer test-token"}
TICKER_META_URL = "/v1/ticker/AAPL/metadata"
TICKER_OHLCV_URL = "/v1/ticker/AAPL/ohlcv"
BULK_URL = "/v1/bulk/ohlcv"


def daily_df(days: int = 300, end: str = "2026-11-06", adjusted: bool = False) -> pd.DataFrame:
    """Bar fixture.

    adjusted=False mirrors yfinance auto_adjust=True: no explicit 'Adj Close'
    column (close is already back-adjusted).
    adjusted=True mirrors auto_adjust=False: 'Adj Close' present and scaled
    0.97 x close.
    """
    rng = pd.bdate_range(end=end, periods=days)
    base = 200.0 + (pd.RangeIndex(days) * 0.5)
    rows: dict[str, object] = {
        "Open": base + 1.0,
        "High": base + 2.0,
        "Low": base - 1.0,
        "Close": base + 0.25,
        "Volume": 1_500_000 + pd.RangeIndex(days) * 111,
        "Dividends": [0.0] * (days - 1) + [0.25],
        "Stock Splits": [0.0] * days,
    }
    if adjusted:
        rows["Adj Close"] = (base + 0.25) * 0.97
    return pd.DataFrame(rows, index=rng)


def intraday_df(rows: int = 20, adjusted: bool = False) -> pd.DataFrame:
    rng = pd.date_range("2026-11-06 09:30", periods=rows, freq="min", tz="America/New_York")
    return daily_df(days=rows, adjusted=adjusted).set_axis(rng)


def info_dict() -> dict[str, Any]:
    return {
        "symbol": "AAPL",
        "shortName": "Apple",
        "longName": "Apple Inc.",
        "quoteType": "EQUITY",
        "market": "us_market",
        "fullExchangeName": "NasdaqGS",
        "exchange": "NMS",
        "exchangeTimezoneName": "America/New_York",
        "currency": "USD",
        "financialCurrency": "USD",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "country": "US",
        "city": "Cupertino",
        "website": "https://www.apple.com",
        "longBusinessSummary": "Company makes phones.",
        "fullTimeEmployees": 164000,
        "currentPrice": 342.37,
        "regularMarketPreviousClose": 342.87,
        "open": 341.12,
        "dayHigh": 344.5,
        "dayLow": 340.11,
        "regularMarketVolume": 39430211,
        "averageDailyVolume3Month": 38855879,
        "averageDailyVolume10Day": 42098723,
        "bid": 342.3,
        "bidSize": 5,
        "ask": 342.4,
        "askSize": 3,
        "fiftyTwoWeekLow": 196.16,
        "fiftyTwoWeekHigh": 357.82,
        "52WeekChange": 0.0397,
        "SandP52WeekChange": 0.0895,
        "allTimeHigh": 357.82,
        "allTimeLow": 0.06,
        "fiftyDayAverage": 268.31,
        "twoHundredDayAverage": 245.7,
        "marketCap": 4210500000000,
        "bookValue": 27.451,
        "priceToBook": 12.17,
        "trailingPE": 33.67,
        "forwardPE": 29.53,
        "sharesOutstanding": 14476062400,
        "floatShares": 13648800000,
        "heldPercentInstitutions": 0.6687,
        "heldPercentInsiders": 0.0006,
        "shortRatio": 5.43,
        "shortPercentOfFloat": 0.0077,
        "dateShortInterest": 1733011200,
        "trailingEps": 10.16,
        "forwardEps": 9.14,
        "earningsTimestampStart": 1769572800,
        "earningsTimestampEnd": 1769884800,
        "isEarningsDateEstimate": True,
        "dividendRate": 1.08,
        "dividendYield": 0.0031,
        "fiveYearAvgDividendYield": 0.0048,
        "payoutRatio": 0.3526,
        "trailingAnnualDividendRate": 1.08,
        "trailingAnnualDividendYield": 0.0032,
        "exDividendDate": 1698796800,
        "dividendDate": 1704067200,
        "targetMeanPrice": 294.38,
        "targetHighPrice": 377.5,
        "targetLowPrice": 203.0,
        "targetMedianPrice": 295.0,
        "recommendationKey": "buy",
        "recommendationMean": 1.86,
        "numberOfAnalystOpinions": 48,
        "companyOfficers": [{"fullName": "Tim C.", "title": "CEO"}],
        "auditRisk": 5,
    }


def history_meta(sub_name: str = "Apple") -> dict[str, Any]:
    return {
        "symbol": "AAPL",
        "shortName": sub_name,
        "longName": "Apple Inc.",
        "instrumentType": "EQUITY",
        "currency": "USD",
        "timezone": "America/New_York",
        "exchangeName": "NMS",
    }
