"""Daily open-high-low-close bars for the S&P 500 index, validated against FRED closes.

The bars are used only to build range-based volatility measures and the
open-to-close return. The close-to-close target still comes from FRED.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    "?period1=1451606400&period2={period2}&interval=1d&events=div"
)
INDEX_SYMBOL = "%5EGSPC"
ETF_SYMBOL = "SPY"
MIN_RETURN_CORRELATION = 0.99
MARKET_ZONE = ZoneInfo("America/New_York")
MAX_CLOSE_DISAGREEMENT = 0.002
MAX_DISAGREEING_SHARE = 0.005


class OhlcError(ValueError):
    """The bar file is malformed or disagrees with the reference closes."""


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise OhlcError("Bar prices must be positive and finite.")
        if self.low > min(self.open, self.close) + 1e-6 or self.high < max(
            self.open, self.close
        ) - 1e-6:
            raise OhlcError("Bar high/low do not bracket its open/close.")


def parse_chart(path: Path) -> dict[date, Bar]:
    """Parse a saved chart response into bars keyed by New York session date."""
    try:
        result = json.loads(path.read_text(encoding="utf-8"))["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        columns = zip(
            result["timestamp"],
            quote["open"],
            quote["high"],
            quote["low"],
            quote["close"],
            strict=True,
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise OhlcError("Unrecognized chart response layout.") from error
    bars: dict[date, Bar] = {}
    for stamp, opened, high, low, close in columns:
        if None in (opened, high, low, close):
            continue
        session = datetime.fromtimestamp(stamp, MARKET_ZONE).date()
        if session in bars:
            raise OhlcError(f"Duplicate bar for {session}.")
        bars[session] = Bar(float(opened), float(high), float(low), float(close))
    if not bars:
        raise OhlcError("Chart response holds no complete bar.")
    return bars


def validate_against_closes(
    bars: dict[date, Bar], reference: dict[date, float]
) -> dict[str, object]:
    """Require the bar closes to agree with an independent close series."""
    common = sorted(set(bars).intersection(reference))
    if len(common) < 250:
        raise OhlcError("Too few common sessions to validate the bars.")
    gaps = [abs(bars[day].close / reference[day] - 1.0) for day in common]
    disagreeing = sum(gap > 1e-4 for gap in gaps)
    if max(gaps) > MAX_CLOSE_DISAGREEMENT or disagreeing / len(common) > MAX_DISAGREEING_SHARE:
        raise OhlcError("Bar closes disagree with the reference closes.")
    return {
        "common_sessions": len(common),
        "max_relative_close_gap": max(gaps),
        "sessions_over_1bp": disagreeing,
    }


def parse_dividends(path: Path) -> dict[date, float]:
    """Cash dividends by ex-date from a saved chart response; empty when none are listed."""
    result = json.loads(path.read_text(encoding="utf-8"))["chart"]["result"][0]
    events = result.get("events", {}).get("dividends", {})
    return {
        datetime.fromtimestamp(int(item["date"]), MARKET_ZONE).date(): float(item["amount"])
        for item in events.values()
    }


def validate_tracking(bars: dict[date, Bar], reference: dict[date, float]) -> dict[str, object]:
    """Require an ETF's close-to-close returns to track the reference index closely."""
    common = sorted(set(bars).intersection(reference))
    if len(common) < 250:
        raise OhlcError("Too few common sessions to validate tracking.")
    etf = [math.log(bars[b].close / bars[a].close) for a, b in zip(common, common[1:], strict=False)]
    index = [math.log(reference[b] / reference[a]) for a, b in zip(common, common[1:], strict=False)]
    mean_etf, mean_index = sum(etf) / len(etf), sum(index) / len(index)
    covariance = sum((x - mean_etf) * (y - mean_index) for x, y in zip(etf, index, strict=True))
    scale = math.sqrt(
        sum((x - mean_etf) ** 2 for x in etf) * sum((y - mean_index) ** 2 for y in index)
    )
    correlation = covariance / scale
    if correlation < MIN_RETURN_CORRELATION:
        raise OhlcError("ETF returns do not track the reference index.")
    return {"common_sessions": len(common), "return_correlation": correlation}


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
