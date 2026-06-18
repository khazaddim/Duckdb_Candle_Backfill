from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Candle:
    provider: str
    market_type: str
    symbol: str
    timeframe_seconds: int
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    raw_json: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class TimeRange:
    start_ts: int
    end_ts: int