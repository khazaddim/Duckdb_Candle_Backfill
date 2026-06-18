from __future__ import annotations

import asyncio
from pathlib import Path

from duckdb_candle_backfill import (
    BackfillConfig,
    Candle,
    TimeRange,
    connect_duckdb,
    create_backfill_job,
    enqueue_backfill_tasks,
    initialize_schema,
    insert_candles,
)


def build_config(database_path: Path) -> BackfillConfig:
    return BackfillConfig(
        provider="simulated",
        market_type="spot",
        symbol="BTC-USD",
        timeframe_seconds=60,
        start_ts=1_700_000_000,
        end_ts=1_700_003_600,
        duckdb_path=database_path,
        max_retries_per_gap=4,
    )


async def test_initialize_schema_creates_tables_and_indexes(tmp_path: Path) -> None:
    """Verify schema initialization creates required tables and supporting indexes."""
    database_path = tmp_path / "schema_test.duckdb"
    storage = connect_duckdb(database_path)

    try:
        await initialize_schema(storage)

        table_rows = await storage.fetch_all(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
            """
        )
        index_rows = await storage.fetch_all(
            "SELECT index_name FROM duckdb_indexes() WHERE schema_name = 'main' ORDER BY index_name"
        )
    finally:
        await storage.close()

    assert {row[0] for row in table_rows} >= {"backfill_jobs", "backfill_tasks", "candles"}
    assert {row[0] for row in index_rows} >= {
        "idx_backfill_tasks_job_status",
        "idx_backfill_tasks_status_priority",
        "idx_candles_lookup",
    }


async def test_create_job_and_enqueue_tasks_persist_metadata(tmp_path: Path) -> None:
    """Verify job creation and task enqueue persist expected metadata values."""
    database_path = tmp_path / "job_task_test.duckdb"
    storage = connect_duckdb(database_path)
    config = build_config(database_path)

    try:
        await initialize_schema(storage)
        job_id = await create_backfill_job(storage, config, aligned_start=1_700_000_020, aligned_end=1_700_003_560)
        inserted_tasks = await enqueue_backfill_tasks(
            storage,
            job_id,
            config,
            [TimeRange(1_700_000_020, 1_700_000_620), TimeRange(1_700_000_680, 1_700_001_280)],
            task_type="initial",
        )

        job_row = await storage.fetch_one(
            """
            SELECT provider, market_type, symbol, timeframe_seconds, requested_start, requested_end,
                   aligned_start, aligned_end, status, max_retries
            FROM backfill_jobs
            WHERE job_id = ?
            """,
            [job_id],
        )
        task_rows = await storage.fetch_all(
            """
            SELECT range_start, range_end, task_type, status, retry_count, max_retries
            FROM backfill_tasks
            WHERE job_id = ?
            ORDER BY range_start
            """,
            [job_id],
        )
    finally:
        await storage.close()

    assert inserted_tasks == 2
    assert job_row == (
        "simulated",
        "spot",
        "BTC-USD",
        60,
        1_700_000_000,
        1_700_003_600,
        1_700_000_020,
        1_700_003_560,
        "pending",
        4,
    )
    assert task_rows == [
        (1_700_000_020, 1_700_000_620, "initial", "pending", 0, 4),
        (1_700_000_680, 1_700_001_280, "initial", "pending", 0, 4),
    ]


async def test_insert_candles_is_idempotent(tmp_path: Path) -> None:
    """Verify duplicate candle inserts do not create duplicate stored rows."""
    database_path = tmp_path / "candles_test.duckdb"
    storage = connect_duckdb(database_path)

    candles = [
        Candle("simulated", "spot", "BTC-USD", 60, 1000, 1.0, 2.0, 0.5, 1.5, 10.0, {"source": 1}),
        Candle("simulated", "spot", "BTC-USD", 60, 1000, 1.0, 2.0, 0.5, 1.5, 10.0, {"source": 1}),
        Candle("simulated", "spot", "BTC-USD", 60, 1060, 1.5, 2.5, 1.0, 2.0, 12.0, {"source": 2}),
    ]

    try:
        await initialize_schema(storage)
        first_inserted = await insert_candles(storage, candles)
        second_inserted = await insert_candles(storage, candles)
        row = await storage.fetch_one("SELECT COUNT(*) FROM candles")
    finally:
        await storage.close()

    assert first_inserted == 2
    assert second_inserted == 0
    assert row == (2,)


async def test_storage_operations_do_not_block_event_loop(tmp_path: Path) -> None:
    """Verify DuckDB work runs off-loop so a heartbeat coroutine keeps ticking."""
    database_path = tmp_path / "loop_test.duckdb"
    storage = connect_duckdb(database_path)
    heartbeat_ticks = 0
    stop = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal heartbeat_ticks
        while not stop.is_set():
            heartbeat_ticks += 1
            await asyncio.sleep(0.001)

    try:
        await initialize_schema(storage)
        task = asyncio.create_task(heartbeat())
        await storage.fetch_one("SELECT SUM(i) FROM range(50000000) AS t(i)")
        stop.set()
        await task
    finally:
        await storage.close()

    assert heartbeat_ticks > 0