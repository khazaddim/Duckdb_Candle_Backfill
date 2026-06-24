from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

import duckdb

from .config import BackfillConfig
from .models import Candle, TimeRange

T = TypeVar("T")


class DuckDBStorage:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # DuckDB work is serialized through one dedicated worker thread:
        # this preserves single-writer behavior and keeps blocking DB calls
        # off the asyncio event-loop thread.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="duckdb-backfill")
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._closed = False

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._closed:
            raise RuntimeError("storage connection is closed")
        if self._connection is None:
            self._connection = duckdb.connect(str(self.database_path))
        return self._connection

    async def run(self, operation: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: operation(self._get_connection(), *args, **kwargs),
        )

    async def fetch_one(self, query: str, parameters: Sequence[Any] | None = None) -> tuple[Any, ...] | None:
        return await self.run(_fetch_one_sync, query, tuple(parameters or ()))

    async def fetch_all(self, query: str, parameters: Sequence[Any] | None = None) -> list[tuple[Any, ...]]:
        return await self.run(_fetch_all_sync, query, tuple(parameters or ()))

    async def close(self) -> None:
        if self._closed:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._close_sync)
        self._executor.shutdown(wait=True)
        self._closed = True

    def _close_sync(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def connect_duckdb(database_path: str | Path) -> DuckDBStorage:
    return DuckDBStorage(database_path)


async def initialize_schema(connection: DuckDBStorage) -> None:
    await connection.run(_initialize_schema_sync)


async def create_backfill_job(
    connection: DuckDBStorage,
    config: BackfillConfig,
    aligned_start: int,
    aligned_end: int,
) -> int:
    return await connection.run(_create_backfill_job_sync, config, aligned_start, aligned_end)


async def enqueue_backfill_tasks(
    connection: DuckDBStorage,
    job_id: int,
    config: BackfillConfig,
    ranges: Sequence[TimeRange],
    task_type: str,
) -> int:
    return await connection.run(_enqueue_backfill_tasks_sync, job_id, config, list(ranges), task_type)


async def insert_candles(connection: DuckDBStorage, candles: Sequence[Candle]) -> int:
    return await connection.run(_insert_candles_sync, list(candles))


def _initialize_schema_sync(connection: duckdb.DuckDBPyConnection) -> None:
    schema_path = Path(__file__).with_name("sql") / "duckdb_schema.sql"
    connection.execute(schema_path.read_text(encoding="utf-8"))


def _create_backfill_job_sync(
    connection: duckdb.DuckDBPyConnection,
    config: BackfillConfig,
    aligned_start: int,
    aligned_end: int,
) -> int:
    job_id = connection.execute("SELECT nextval('backfill_job_id_seq')").fetchone()[0]
    connection.execute(
        """
        INSERT INTO backfill_jobs (
            job_id,
            provider,
            market_type,
            symbol,
            timeframe_seconds,
            requested_start,
            requested_end,
            aligned_start,
            aligned_end,
            status,
            max_retries,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        [
            job_id,
            config.provider,
            config.market_type,
            config.symbol,
            config.timeframe_seconds,
            config.start_ts,
            config.end_ts,
            aligned_start,
            aligned_end,
            "pending",
            config.max_retries_per_gap,
        ],
    )
    return int(job_id)


def _enqueue_backfill_tasks_sync(
    connection: duckdb.DuckDBPyConnection,
    job_id: int,
    config: BackfillConfig,
    ranges: list[TimeRange],
    task_type: str,
) -> int:
    if not ranges:
        return 0

    rows = [
        (
            job_id,
            task_type,
            config.provider,
            config.market_type,
            config.symbol,
            config.timeframe_seconds,
            item.start_ts,
            item.end_ts,
            100,
            "pending",
            0,
            config.max_retries_per_gap,
            None,
            None,
            None,
        )
        for item in ranges
    ]

    connection.executemany(
        """
        INSERT INTO backfill_tasks (
            job_id,
            task_type,
            provider,
            market_type,
            symbol,
            timeframe_seconds,
            range_start,
            range_end,
            priority,
            status,
            retry_count,
            max_retries,
            last_error,
            claimed_by,
            claimed_at,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        rows,
    )
    return len(rows)


def _insert_candles_sync(connection: duckdb.DuckDBPyConnection, candles: list[Candle]) -> int:
    if not candles:
        return 0

    unique_keys = _unique_candle_keys(candles)
    existing_count = _count_existing_candle_keys(connection, unique_keys)
    rows = [
        (
            candle.provider,
            candle.market_type,
            candle.symbol,
            candle.timeframe_seconds,
            candle.timestamp,
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            json.dumps(candle.raw_json, sort_keys=True) if candle.raw_json is not None else None,
        )
        for candle in candles
    ]
    connection.executemany(
        """
        INSERT INTO candles (
            provider,
            market_type,
            symbol,
            timeframe_seconds,
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (provider, market_type, symbol, timeframe_seconds, timestamp) DO NOTHING
        """,
        rows,
    )
    return len(unique_keys) - existing_count


def _unique_candle_keys(candles: Sequence[Candle]) -> list[tuple[str, str, str, int, int]]:
    seen: dict[tuple[str, str, str, int, int], None] = {}
    for candle in candles:
        seen[(
            candle.provider,
            candle.market_type,
            candle.symbol,
            candle.timeframe_seconds,
            candle.timestamp,
        )] = None
    return list(seen)


def _count_existing_candle_keys(
    connection: duckdb.DuckDBPyConnection,
    unique_keys: Sequence[tuple[str, str, str, int, int]],
) -> int:
    if not unique_keys:
        return 0

    placeholders = ", ".join(["(?, ?, ?, ?, ?)"] * len(unique_keys))
    parameters: list[Any] = []
    for key in unique_keys:
        parameters.extend(key)

    row = connection.execute(
        f"""
        WITH incoming(provider, market_type, symbol, timeframe_seconds, timestamp) AS (
            VALUES {placeholders}
        )
        SELECT COUNT(*)
        FROM incoming
        JOIN candles USING (provider, market_type, symbol, timeframe_seconds, timestamp)
        """,
        parameters,
    ).fetchone()
    return int(row[0])


def _fetch_one_sync(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[Any],
) -> tuple[Any, ...] | None:
    return connection.execute(query, parameters).fetchone()


def _fetch_all_sync(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[Any],
) -> list[tuple[Any, ...]]:
    return connection.execute(query, parameters).fetchall()