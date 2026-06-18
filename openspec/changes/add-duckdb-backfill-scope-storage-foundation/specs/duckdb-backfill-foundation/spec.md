## ADDED Requirements

### Requirement: V1 Scope Boundary Definition
The backfill module SHALL define and preserve a v1 scope boundary that includes only single-provider, single-symbol, single-timeframe jobs running in one owning Python process with DuckDB-backed durable state.

#### Scenario: In-scope behavior is explicitly defined
- **WHEN** maintainers review the v1 proposal and implementation checklist
- **THEN** the documented in-scope items include one provider adapter at a time, one symbol per job, one timeframe per job, DuckDB-backed jobs/tasks/candles, SQL-based validation, and async workers in one process

#### Scenario: Out-of-scope behavior is explicitly defined
- **WHEN** maintainers review v1 exclusions
- **THEN** GUI integration, multi-provider orchestration, multi-symbol scheduling, distributed workers, and database-level multi-worker claiming are marked out of scope

### Requirement: DuckDB Foundation Schema
The system SHALL provide a DuckDB schema foundation for historical backfill state with normalized candle storage and durable job/task metadata.

#### Scenario: Required tables exist
- **WHEN** schema initialization runs against a new DuckDB file
- **THEN** tables for candles, backfill_jobs, and backfill_tasks are created if missing

#### Scenario: Required indexes exist
- **WHEN** schema initialization completes
- **THEN** indexes exist for candle lookup key patterns and task queue inspection by status and priority

### Requirement: Idempotent Candle Writes
The system SHALL store candles using idempotent insert semantics keyed by provider, market_type, symbol, timeframe_seconds, and timestamp.

#### Scenario: Duplicate candle insert does not create duplicate rows
- **WHEN** the same candle key is inserted multiple times
- **THEN** only one row remains for that key and the operation completes without data corruption

### Requirement: Backfill Job And Task Storage Primitives
The storage layer SHALL expose primitives to create backfill jobs and enqueue backfill tasks in DuckDB.

#### Scenario: Job creation persists aligned range metadata
- **WHEN** create_backfill_job() is called with normalized parameters
- **THEN** a new backfill_jobs row is persisted with requested and aligned range fields and an initial status

#### Scenario: Task enqueue persists planned ranges
- **WHEN** enqueue_backfill_tasks() is called with planned ranges
- **THEN** one backfill_tasks row is created per range with task type, priority, retry defaults, and pending status

### Requirement: Event-Loop-Safe DuckDB Access
The storage layer SHALL prevent blocking DuckDB operations from running on the main asyncio event-loop thread.

#### Scenario: Blocking DB calls are offloaded
- **WHEN** async storage methods execute schema, insert, or enqueue queries
- **THEN** the underlying synchronous DuckDB work is executed via thread offloading or an equivalent single-worker off-loop mechanism

#### Scenario: Host loop remains responsive during DB activity
- **WHEN** a heartbeat coroutine runs concurrently with backfill storage operations
- **THEN** heartbeat ticks continue advancing without prolonged stalls attributable to direct on-loop DuckDB execution
