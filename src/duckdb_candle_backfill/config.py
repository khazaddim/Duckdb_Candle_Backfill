from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BackfillConfig:
    provider: str
    market_type: str
    symbol: str
    timeframe_seconds: int
    start_ts: int
    end_ts: int
    duckdb_path: Path
    max_candles_per_request: int = 300
    max_concurrent_requests: int = 5
    max_retries_per_gap: int = 3
    request_timeout_seconds: int = 30
    retry_backoff_seconds: float = 1.0
    split_large_gaps_threshold: int = 100
    store_raw_json: bool = False