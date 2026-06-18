# Change: Add DuckDB Backfill Foundation

## Why
The backfill module needs a clear v1 boundary and a stable local persistence model before provider orchestration and retry logic are added. Without this foundation, later milestones risk rework in schema design, task-state semantics, async integration behavior, and test strategy.

This change is based on the repository design in `backfill_module_design_duckdb.md`, specifically the "Change 1 - Freeze scope and storage foundation" grouping and the sections covering DuckDB constraints, schema, and storage-layer async integration.

This proposal is intentionally self-sufficient for Change 1 review. It captures the v1 boundary, the minimum durable data model, the required storage primitives, and the validation bar without requiring the reviewer to reconstruct those details from the larger design document.

## What Changes
- Freeze v1 scope for the DuckDB backfill module with explicit in-scope and out-of-scope definitions.
- Define the foundational DuckDB schema for candles, backfill jobs, and backfill tasks.
- Define the required indexes and keying model needed for idempotent storage and SQL inspection.
- Define async storage facade requirements that keep blocking DuckDB work off the host asyncio event-loop thread.
- Define the required storage primitives for database connection, schema initialization, job creation, task enqueue, and candle insertion.
- Define the Change 1 quality bar for correctness and event-loop responsiveness.

## V1 Scope Summary

### In Scope
- One provider adapter at a time.
- One symbol per backfill job.
- One timeframe per backfill job.
- One owning Python process coordinating state for a job.
- A local DuckDB file as the durable system of record for candles, jobs, and tasks.
- SQL-inspectable persisted state suitable for later validation and dispatch work.
- Async-facing storage helpers that offload blocking DuckDB operations from the main event-loop thread.
- Idempotent candle persistence keyed by provider, market type, symbol, timeframe, and timestamp.

### Out Of Scope
- Multi-provider orchestration in one run.
- Multi-symbol scheduling in one job.
- Cross-process or cross-machine worker coordination.
- Database-level worker-claim semantics such as PostgreSQL row locking.
- Provider HTTP logic and response normalization.
- Validation queries, retry scheduling, and full backfill runner behavior.
- GUI integration, progress displays, and user-facing controls.
- Market-calendar-specific gap policies.

## Foundation Summary

### Required persistent entities
- `candles`: canonical OHLCV storage.
- `backfill_jobs`: durable record of requested range, aligned range, status, and retry settings.
- `backfill_tasks`: durable record of planned work ranges and task lifecycle metadata.

### Required storage primitives
- `connect_duckdb(database_path)`
- `initialize_schema(connection)`
- `create_backfill_job(connection, config, aligned_start, aligned_end)`
- `enqueue_backfill_tasks(connection, job_id, config, ranges, task_type)`
- `insert_candles(connection, candles)`

### Required quality bar
- Duplicate candle writes are harmless.
- Task rows are inspectable with SQL after enqueue.
- Job rows preserve both requested and aligned range metadata.
- Storage methods do not block the host asyncio event loop.

## Review Focus
- Confirm the v1 boundary is narrow enough to prevent orchestration and GUI scope creep.
- Confirm DuckDB is the explicit portable local backend for Change 1.
- Confirm the schema captures the minimum durable state needed for later planning, dispatch, and retry work.
- Confirm the async integration rule is strict enough to protect a DearCyGui-hosted event loop from DuckDB stalls.
- Confirm the storage primitives are concrete enough to guide implementation without prematurely specifying later changes.

## Acceptance Summary
- Change 1 documents in-scope and out-of-scope behavior clearly.
- A fresh DuckDB file can be initialized with the required tables and indexes.
- Job rows, task rows, and candle rows can be persisted through defined primitives.
- Repeated candle inserts do not create duplicates or corrupt prior canonical rows.
- Tests demonstrate both storage correctness and event-loop responsiveness.

## Impact
- Affected specs: duckdb-backfill-foundation
- Affected code (planned): storage_duckdb.py, sql/duckdb_schema.sql, sql/duckdb_queries.sql, config.py, models.py
- Breaking changes: none (new capability)

## Source References
- `backfill_module_design_duckdb.md`
- Milestone 0 - Freeze v1 scope
- Milestone 1 - Schema and storage foundation
- Suggested OpenSpec Change Groupings -> Change 1 - Freeze scope and storage foundation
