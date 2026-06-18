## Context
This change establishes the first implementation slice for a DuckDB-based historical candle backfill module. It combines scope freeze and storage foundation so reviewers can validate the project boundary, durable data model, and event-loop-safe storage behavior before provider orchestration, validation queries, and retry behavior are introduced.

The source design for this change is the repository document `backfill_module_design_duckdb.md`. This OpenSpec design is narrower than the source document, but it is intended to be self-sufficient for Change 1 itself.

The host environment is an asyncio application and may include GUI rendering on the same loop. Blocking DuckDB calls therefore cannot run directly on the main event-loop thread.

## Goals / Non-Goals
- Goals:
  - Define explicit v1 scope boundaries and exclusions.
  - Establish durable local DuckDB schema for candles, jobs, and tasks.
  - Require idempotent candle storage and durable task enqueue primitives.
  - Require async-facing storage behavior that offloads blocking DuckDB operations.
  - Establish the testing and acceptance bar for the storage foundation.
- Non-Goals:
  - Provider HTTP logic and response normalization.
  - Validation queries and retry engine semantics.
  - Multi-process or distributed task claiming.
  - GUI integration and status rendering.

## Scope Boundary

### Included in Change 1
- Durable DuckDB storage for candle rows, backfill jobs, and planned backfill tasks.
- Connection and schema initialization helpers for a local `.duckdb` database file.
- Storage-layer contracts for job creation, task enqueue, and candle insertion.
- Schema-level support for later single-process orchestration and SQL inspection.
- Tests proving the storage layer behaves correctly and does not stall the host event loop.

### Excluded from Change 1
- Simulated provider server behavior.
- Provider adapter implementations.
- Missing-timestamp queries, gap compression, and summary queries.
- Worker dispatch loops and task state transitions beyond initial enqueue semantics.
- Public orchestration entrypoints such as `run_backfill(...)`.
- Retry task generation and retry exhaustion semantics.

## Architecture Constraints
- DuckDB is embedded and synchronous from the Python driver's perspective.
- v1 assumes one owning Python process coordinates the job lifecycle.
- The storage layer must expose async methods even though DuckDB work is synchronous underneath.
- Persisted state must remain SQL-inspectable for later milestones.
- The data model must be minimal, but stable enough to support later validation and dispatch work without immediate redesign.

## Data Model

### Candles
Purpose: durable canonical OHLCV storage.

Required fields:
- `provider`
- `market_type`
- `symbol`
- `timeframe_seconds`
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `fetched_at`
- `raw_json`

Required behavior:
- The primary key is the compound candle identity: `provider`, `market_type`, `symbol`, `timeframe_seconds`, `timestamp`.
- `timestamp` represents candle open time in Unix epoch seconds.
- Repeated inserts for the same key are idempotent.
- `raw_json` may use DuckDB `JSON` or `TEXT` so long as the storage choice is explicit and compatible with the local toolchain.

### Backfill Jobs
Purpose: durable record of a requested backfill after range normalization.

Required fields:
- `job_id`
- `provider`
- `market_type`
- `symbol`
- `timeframe_seconds`
- `requested_start`
- `requested_end`
- `aligned_start`
- `aligned_end`
- `status`
- `max_retries`
- `created_at`
- `updated_at`

Required behavior:
- Each job records both requested and aligned ranges.
- Each job preserves enough status and retry-budget information for later orchestration work.
- `job_id` is durable and generated using DuckDB-compatible identity semantics.

### Backfill Tasks
Purpose: durable record of planned work ranges derived from a job.

Required fields:
- `task_id`
- `job_id`
- `task_type`
- `provider`
- `market_type`
- `symbol`
- `timeframe_seconds`
- `range_start`
- `range_end`
- `priority`
- `status`
- `retry_count`
- `max_retries`
- `last_error`
- `claimed_by`
- `claimed_at`
- `created_at`
- `updated_at`

Required behavior:
- Tasks are initially stored in `pending` state.
- Tasks carry enough metadata for later single-process dispatcher and worker logic.
- Each task is associated with a job through durable relational linkage.

## Required Indexes
- Candle lookup index on `provider`, `market_type`, `symbol`, `timeframe_seconds`, and `timestamp`.
- Task queue inspection index on `status`, `priority`, and `created_at`.
- Job-task inspection index on `job_id` and `status`.

## Storage Interface Expectations

### Required primitives
- `connect_duckdb(database_path: str)`
- `initialize_schema(connection) -> None`
- `create_backfill_job(connection, config, aligned_start, aligned_end) -> int`
- `enqueue_backfill_tasks(connection, job_id, config, ranges, task_type) -> int`
- `insert_candles(connection, candles) -> int`

### Contract expectations
- `connect_duckdb(...)` opens or creates the local database file.
- `initialize_schema(...)` is safe to run repeatedly and creates all required schema objects if missing.
- `create_backfill_job(...)` persists requested and aligned range metadata and returns a durable job identifier.
- `enqueue_backfill_tasks(...)` creates one task row per planned range and returns the number of persisted tasks or an equivalent success result.
- `insert_candles(...)` performs idempotent persistence and returns an inserted-row count or equivalent result that distinguishes successful handling from failure.

## Async Integration Strategy
- Public storage-facing methods are async.
- Underlying synchronous DuckDB calls execute via `asyncio.to_thread(...)` or an equivalent dedicated off-loop worker mechanism.
- The implementation may serialize DB work for correctness, but it may not block the main event-loop thread while queries or inserts run.

### Acceptable implementation patterns
- Async facade that delegates each blocking DB call through `asyncio.to_thread(...)`.
- Dedicated database worker thread receiving requests from async callers.
- Single-writer off-loop worker pattern, provided callers still observe async non-blocking behavior.

### Unacceptable implementation patterns
- Executing `duckdb.execute(...)` directly inside async coroutines on the event-loop thread.
- Treating single-process ownership as permission to freeze the host loop during inserts, schema work, or durable updates.

## Decisions
- Decision: Use a local DuckDB file as the durable v1 backend.
  - Rationale: portability, inspectable SQL state, and no external server dependency.
- Decision: Keep queue ownership in one Python process for v1.
  - Rationale: avoids database row-lock semantics that are outside the intended DuckDB portability model.
- Decision: Require async storage facade over synchronous DuckDB work.
  - Rationale: preserve host event-loop responsiveness.
- Decision: Limit this change to scope and storage-foundation concerns.
  - Rationale: keep the first change reviewable while still defining the prerequisites for later milestones.

## Implementation Notes
- Placeholder syntax must be DuckDB-compatible.
- Timestamps and identity generation must use DuckDB-compatible types and expressions.
- Change 1 should not require validation SQL, retry range compression, task selection queries, or worker-claim semantics.
- The schema should be portable and default to the database's default namespace unless a compelling reason emerges otherwise.

## Risks / Trade-offs
- Risk: Direct synchronous DB calls inside async code can freeze the host GUI loop.
  - Mitigation: require thread offload or a dedicated off-loop DB worker.
- Risk: Scope drift into orchestration concerns during foundation work.
  - Mitigation: explicit included and excluded behavior in this change.
- Risk: Under-specifying primitive contracts now can force rewrites later.
  - Mitigation: define minimum required fields, return expectations, and idempotency semantics in this document.
- Risk: Over-specifying later behavior too early can slow delivery.
  - Mitigation: defer provider, validation, retry, and runner details to later changes while preserving only the storage contracts they depend on.

## Test Strategy For Change 1
- Initialize a fresh temporary `.duckdb` file and verify schema creation succeeds.
- Create a backfill job and verify requested and aligned range metadata persist correctly.
- Enqueue multiple planned ranges and verify one task row is stored per range.
- Insert duplicate candle payloads and verify only one canonical row exists per candle key.
- Run storage operations concurrently with a heartbeat coroutine and verify the heartbeat keeps advancing.

## Migration Plan
1. Approve this change proposal and deltas.
2. Implement schema DDL and index creation helpers.
3. Implement connection and storage primitives.
4. Add focused storage correctness and event-loop responsiveness tests.
5. Use this foundation as prerequisite for subsequent provider and dispatch changes.

## Open Questions
- Should raw payload storage default to `JSON` or `TEXT` for widest local compatibility?
- Should any future attempts table be deferred entirely to a later change, or described now as a future extension only?

## Deferred To Later Changes
- Simulated provider server and provider adapter behavior.
- SQL gap detection and job summary queries.
- Pending-task selection and running/completed/failed task lifecycle transitions.
- Retry task generation and retry exhaustion semantics.
- GUI progress helpers, cancellation ergonomics, and host-facing status APIs.

## Source References
- `backfill_module_design_duckdb.md`
- "Why a DuckDB Variant"
- "Recommended Database Schema"
- "Storage Layer Design"
- "Implementation Milestones" -> Milestone 0 and Milestone 1
- "Suggested OpenSpec Change Groupings" -> Change 1
