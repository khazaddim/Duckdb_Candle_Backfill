# Change: Add DuckDB Backfill Scope And Storage Foundation

## Why
The backfill module needs a clear v1 boundary and a stable local persistence model before provider orchestration and retry logic are added. Without this foundation, later milestones risk rework in schema, task-state semantics, and async integration behavior.

## What Changes
- Freeze v1 scope for the DuckDB backfill module (in-scope and out-of-scope definitions).
- Add foundational DuckDB storage requirements for candles, jobs, and tasks.
- Define required schema objects and indexes for idempotent storage and task inspection.
- Define async storage facade requirements that prevent blocking the host asyncio event loop.
- Define required primitives for creating jobs, enqueuing tasks, and inserting candles.

## Impact
- Affected specs: duckdb-backfill-foundation
- Affected code (planned): storage_duckdb.py, sql/duckdb_schema.sql, sql/duckdb_queries.sql, config.py, models.py
- Breaking changes: none (new capability)
