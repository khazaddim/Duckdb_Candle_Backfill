## ADDED Requirements

### Requirement: V1 Scope Boundary Definition
The backfill module SHALL define and preserve a v1 scope boundary that includes only single-provider, single-symbol, single-timeframe jobs running in one owning Python process with DuckDB-backed durable state.

#### Scenario: In-scope behavior is explicitly defined
- **WHEN** maintainers review the Change 1 proposal and implementation checklist
- **THEN** the documented in-scope items include one provider adapter at a time, one symbol per job, one timeframe per job, DuckDB-backed jobs, tasks, and candles, and async ownership inside one Python process

#### Scenario: Out-of-scope behavior is explicitly defined
- **WHEN** maintainers review Change 1 exclusions
- **THEN** GUI integration, multi-provider orchestration, multi-symbol scheduling, distributed workers, and database-level multi-worker claiming are marked out of scope

#### Scenario: Change 1 excludes retry and provider orchestration behavior
- **WHEN** reviewers evaluate the Change 1 deliverable
- **THEN** provider fetch logic, gap detection, retry scheduling, and full job runner behavior are treated as later changes rather than implicit requirements of this foundation change

### Requirement: DuckDB Foundation Schema
The system SHALL provide a DuckDB schema foundation for historical backfill state with normalized candle storage and durable job and task metadata.

#### Scenario: Required tables exist
- **WHEN** schema initialization runs against a new DuckDB file
- **THEN** tables for `candles`, `backfill_jobs`, and `backfill_tasks` are created if missing

#### Scenario: Required indexes exist
- **WHEN** schema initialization completes
- **THEN** indexes exist for candle lookup key patterns and task queue inspection by status and priority

#### Scenario: Job-task inspection is supported
- **WHEN** a reviewer inspects the schema for later single-process orchestration support
- **THEN** task rows can be filtered by job and status using persisted task metadata and supporting indexes

### Requirement: Required Field Coverage
The schema SHALL persist the minimum field set needed for canonical candle storage and durable job and task records.

#### Scenario: Candle rows persist canonical key fields
- **WHEN** a candle row is stored
- **THEN** the row includes provider, market_type, symbol, timeframe_seconds, timestamp, price fields, and fetch metadata needed for durable canonical storage

#### Scenario: Job rows persist requested and aligned ranges
- **WHEN** a backfill job row is stored
- **THEN** the row includes requested_start, requested_end, aligned_start, aligned_end, status, and retry-budget metadata

#### Scenario: Task rows persist scheduling metadata
- **WHEN** a backfill task row is stored
- **THEN** the row includes job_id, task_type, range_start, range_end, priority, status, retry counters, and claim-tracking fields required for later single-process task dispatch

### Requirement: Idempotent Candle Writes
The system SHALL store candles using idempotent insert semantics keyed by provider, market_type, symbol, timeframe_seconds, and timestamp.

#### Scenario: Duplicate candle insert does not create duplicate rows
- **WHEN** the same candle key is inserted multiple times
- **THEN** only one row remains for that key and the operation completes without data corruption

#### Scenario: Duplicate insert does not corrupt prior canonical data
- **WHEN** an already-stored candle is submitted again through the storage primitive
- **THEN** the operation completes without creating a second row or leaving the database in an inconsistent state

### Requirement: Backfill Job And Task Storage Primitives
The storage layer SHALL expose primitives to connect to DuckDB, initialize schema, create backfill jobs, and enqueue backfill tasks.

#### Scenario: Connection helper opens durable local storage
- **WHEN** `connect_duckdb()` is called with a database path
- **THEN** the storage layer opens or creates the local DuckDB file required for Change 1 persistence

#### Scenario: Storage primitives support repeatable schema initialization
- **WHEN** `initialize_schema()` is called more than once against the same database
- **THEN** required schema objects remain available without destructive side effects

#### Scenario: Job creation persists aligned range metadata
- **WHEN** `create_backfill_job()` is called with normalized parameters
- **THEN** a new `backfill_jobs` row is persisted with requested and aligned range fields and an initial status

#### Scenario: Task enqueue persists planned ranges
- **WHEN** `enqueue_backfill_tasks()` is called with planned ranges
- **THEN** one `backfill_tasks` row is created per range with task type, priority, retry defaults, and pending status

### Requirement: Event-Loop-Safe DuckDB Access
The storage layer SHALL prevent blocking DuckDB operations from running on the main asyncio event-loop thread.

#### Scenario: Blocking DB calls are offloaded
- **WHEN** async storage methods execute schema, insert, or enqueue queries
- **THEN** the underlying synchronous DuckDB work is executed via thread offloading or an equivalent single-worker off-loop mechanism

#### Scenario: Host loop remains responsive during DB activity
- **WHEN** a heartbeat coroutine runs concurrently with backfill storage operations
- **THEN** heartbeat ticks continue advancing without prolonged stalls attributable to direct on-loop DuckDB execution

#### Scenario: Single-process ownership does not weaken loop-safety requirements
- **WHEN** implementers choose a serialized or single-writer storage strategy
- **THEN** the design still requires that blocking DuckDB execution happen off the main event-loop thread
