# Python-Oriented Design: Historical Candle Backfill Module (DuckDB Variant)

## Purpose

This document specifies a database-first Python design for a historical candle backfill module for crypto and stock market data using DuckDB instead of PostgreSQL. The module downloads OHLCV candles asynchronously, stores them in a portable local DuckDB database file, validates completeness against the expected timestamp grid, and retries only missing ranges until the requested backfill is complete or retry limits are reached.

The design is intended to be practical for local development in VS Code and consistent with an `aiohttp` + `duckdb` workflow that is easy to move across machines.

Because this module is expected to run inside a DearCyGui application that already owns an `asyncio` event loop, the backfill API must remain async from the caller's point of view and must not block the event loop while performing DuckDB work.

---

## Why a DuckDB Variant

DuckDB changes the tradeoffs of the original design:

- it removes the need to install and operate a PostgreSQL server
- it makes the backfill state portable as a single `.duckdb` file
- it works well for SQL-heavy validation and local analytics
- it is a strong fit for one-machine, one-process orchestration

It also imposes constraints that should be explicit in the spec:

- v1 should assume a single Python process owns the backfill job
- task claiming should be coordinated in Python rather than via `FOR UPDATE SKIP LOCKED`
- async database I/O should use thread offloading around the synchronous DuckDB driver
- schema, SQL types, and placeholder syntax need DuckDB-compatible forms

---

## Design Goals

### Functional goals
- Download OHLCV candles for a symbol across a requested historical time range.
- Normalize misaligned requested times to valid candle boundaries.
- Insert candles into DuckDB using idempotent writes.
- Detect missing timestamps after initial downloads.
- Compress missing timestamps into contiguous retry ranges.
- Retry only those missing ranges.
- Produce a final summary describing completeness and unresolved gaps.

### Non-functional goals
- Keep the backfill database portable across Windows laptops and other developer machines.
- Preserve SQL-first validation instead of pushing completeness checks into large Python DataFrames.
- Support resumable and repeatable local backfills.
- Remain safe to run inside an already-running `asyncio` application, including DearCyGui-based GUI applications.
- Expose an async public API even though DuckDB access is internally synchronous.
- Avoid blocking the host event loop during database reads, writes, validation, and task-state updates.
- Keep provider-specific logic isolated from the core retry engine.
- Keep the first implementation small enough to build incrementally.

---

## Recommended Module Layout

```text
Macro_Ideas/
  docs/
    backfill_module_design.md
    backfill_module_design_duckdb.md
  market_data/
    __init__.py
    backfill/
      __init__.py
      config.py
      models.py
      providers.py
      planner.py
      storage_duckdb.py
      validator.py
      retry_engine.py
      runner.py
      test_server.py
      sql/
        duckdb_schema.sql
        duckdb_queries.sql
```

### Suggested responsibilities

- `config.py`
  - dataclasses and runtime settings
- `models.py`
  - Python data models for candles, jobs, tasks, gaps, and results
- `providers.py`
  - provider adapter interface and concrete HTTP implementations
- `planner.py`
  - range alignment and initial chunk planning
- `storage_duckdb.py`
  - DuckDB connection management plus insert/query helpers
- `validator.py`
  - thin wrappers over DuckDB validation queries plus light gap/result mapping
- `retry_engine.py`
  - retry scheduling and retry loop behavior
- `runner.py`
  - orchestration entrypoint for a backfill job
- `test_server.py`
  - simulated candle provider for validation and failure-mode testing
- `sql/duckdb_schema.sql`
  - DDL for tables and indexes
- `sql/duckdb_queries.sql`
  - validation, summary, and task update SQL

---

## Core Design Principles

### 1. Database-first ingestion
Candles should be written to DuckDB as soon as they are received. Validation should compare the expected timestamp grid against the database contents for the requested range.

### 2. DuckDB-first validation
Validation should primarily happen in DuckDB, not in Pandas or large in-memory Python structures. Python should remain thin and focus on orchestration, async HTTP I/O, provider normalization, and translating SQL results into retry actions.

### 3. Canonical candle timestamp
Every candle timestamp represents the open time of the candle in Unix epoch seconds.

### 4. Strict timeframe alignment
All candle timestamps must be aligned to the timeframe grid. For a timeframe of `3600`, valid timestamps are exact hour boundaries.

### 5. Idempotent inserts
Repeated downloads must not create duplicate rows or corrupt previously stored data.

### 6. Retry missing ranges only
Retries should operate only on ranges proven to be missing from the database.

### 7. Single-process queue ownership for v1
DuckDB should be treated as durable local state, but Python should own task dispatch and concurrency coordination in v1 rather than relying on database row locking semantics.

### 8. Event-loop-safe async integration
Although DuckDB operations are effectively single-threaded from the module's point of view, the backfill module must still integrate as an async component. It must be safe to run inside an existing `asyncio` loop without freezing GUI rendering, input handling, timers, or other application tasks.

---

## Why Validation Should Primarily Happen in DuckDB

For this project, DuckDB is still a better place than Python DataFrames for most validation tasks.

### Benefits
- Avoids building large expected timestamp arrays in Python.
- Keeps the local database file as the source of truth for job completeness.
- Makes validation logic queryable and inspectable with SQL.
- Supports resumability and crash recovery without running a separate server.
- Makes progress reporting easier for a future GUI or notebook workflow.
- Preserves portability by bundling state into one local file.

### Validation tasks that belong in DuckDB
- missing timestamp detection
- contiguous gap detection
- off-grid timestamp checks
- duplicate prevention via primary key or unique constraint
- job progress summary queries
- durable storage of jobs, tasks, and attempts

### Validation tasks that remain in Python
- HTTP/API requests
- provider-specific response parsing and normalization
- scheduling retries and backoff policies
- coordinating which task runs next
- creating new retry tasks from SQL query results
- GUI-facing orchestration and user interaction

The intended architecture is:
- DuckDB = local durable state plus validation source of truth
- Python = async orchestration, provider adapters, and task coordination

---

## Key Architectural Changes from the PostgreSQL Version

The original PostgreSQL-oriented spec needs these concrete changes to fit DuckDB:

1. Replace `asyncpg` pool usage with a DuckDB connection wrapper.
2. Replace server-based connection strings with a file path such as `market_data.duckdb`.
3. Replace `JSONB` columns with `JSON` or `TEXT` columns storing serialized JSON.
4. Replace `TIMESTAMPTZ` and `BIGSERIAL` with DuckDB-compatible types and identity generation.
5. Replace `$1`, `$2` placeholders with `?` placeholders.
6. Replace database-side task claiming via `FOR UPDATE SKIP LOCKED` with Python-owned dispatch.
7. Replace assumptions about many concurrent DB writers with a single-process writer model.
8. Replace `NOW()` and other server-oriented SQL expectations with DuckDB-compatible expressions such as `CURRENT_TIMESTAMP`.
9. Rewrite integration tests to create temporary `.duckdb` files instead of requiring a live PostgreSQL instance.
10. Require event-loop-safe async wrappers around synchronous DuckDB calls so GUI applications are not blocked.

---

## Recommended Database Schema

Use either the default schema or a lightweight schema namespace if desired. For maximum portability and simplicity, v1 can avoid a named schema and keep all tables in the default namespace.

### Candles table

```sql
CREATE TABLE IF NOT EXISTS candles (
    provider VARCHAR NOT NULL,
    market_type VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    timestamp BIGINT NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    volume DOUBLE,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_json JSON,
    PRIMARY KEY (provider, market_type, symbol, timeframe_seconds, timestamp)
);
```

If the local DuckDB build or client code path makes `JSON` inconvenient, `raw_json TEXT` is also acceptable for v1.

### Backfill jobs table

```sql
CREATE SEQUENCE IF NOT EXISTS backfill_job_id_seq;

CREATE TABLE IF NOT EXISTS backfill_jobs (
    job_id BIGINT PRIMARY KEY DEFAULT nextval('backfill_job_id_seq'),
    provider VARCHAR NOT NULL,
    market_type VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    requested_start BIGINT NOT NULL,
    requested_end BIGINT NOT NULL,
    aligned_start BIGINT NOT NULL,
    aligned_end BIGINT NOT NULL,
    status VARCHAR NOT NULL,
    max_retries INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

### Backfill tasks table

```sql
CREATE SEQUENCE IF NOT EXISTS backfill_task_id_seq;

CREATE TABLE IF NOT EXISTS backfill_tasks (
    task_id BIGINT PRIMARY KEY DEFAULT nextval('backfill_task_id_seq'),
    job_id BIGINT NOT NULL,
    task_type VARCHAR NOT NULL,
    provider VARCHAR NOT NULL,
    market_type VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    range_start BIGINT NOT NULL,
    range_end BIGINT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    status VARCHAR NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error VARCHAR,
    claimed_by VARCHAR,
    claimed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES backfill_jobs(job_id)
);
```

### Optional backfill attempts table

```sql
CREATE SEQUENCE IF NOT EXISTS backfill_attempt_id_seq;

CREATE TABLE IF NOT EXISTS backfill_attempts (
    attempt_id BIGINT PRIMARY KEY DEFAULT nextval('backfill_attempt_id_seq'),
    job_id BIGINT NOT NULL,
    task_id BIGINT,
    range_start BIGINT NOT NULL,
    range_end BIGINT NOT NULL,
    attempt_number INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    requested_candles INTEGER,
    received_candles INTEGER,
    missing_after_attempt INTEGER,
    error_message VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES backfill_jobs(job_id),
    FOREIGN KEY (task_id) REFERENCES backfill_tasks(task_id)
);
```

### Suggested indexes

```sql
CREATE INDEX IF NOT EXISTS idx_candles_lookup
    ON candles (provider, market_type, symbol, timeframe_seconds, timestamp);

CREATE INDEX IF NOT EXISTS idx_backfill_tasks_status_priority
    ON backfill_tasks (status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_backfill_tasks_job_status
    ON backfill_tasks (job_id, status);
```

---

## Python Data Models

### Configuration

```python
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
```

### Candle model

```python
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
```

### Planned range

```python
from dataclasses import dataclass

@dataclass(slots=True)
class TimeRange:
    start_ts: int
    end_ts: int
```

### Gap model

```python
from dataclasses import dataclass

@dataclass(slots=True)
class GapRange:
    start_ts: int
    end_ts: int
    candle_count: int
    retry_count: int = 0
```

### Final result

```python
from dataclasses import dataclass

@dataclass(slots=True)
class BackfillResult:
    job_id: int
    status: str
    expected_candles: int
    stored_candles: int
    missing_candles: int
    retry_attempts: int
    unresolved_gaps: list[GapRange]
```

---

## Timestamp Alignment Rules

These rules are unchanged from the PostgreSQL variant.

### Canonical alignment
For timeframe `g` seconds:

```python
def align_timestamp_down(ts: int, g: int) -> int:
    return (ts // g) * g
```

### Requested range normalization

```python
def normalize_range(start_ts: int, end_ts: int, timeframe_seconds: int) -> tuple[int, int]:
    aligned_start = align_timestamp_down(start_ts, timeframe_seconds)
    aligned_end = align_timestamp_down(end_ts, timeframe_seconds)
    if aligned_end < aligned_start:
        raise ValueError("aligned_end must be >= aligned_start")
    return aligned_start, aligned_end
```

### Expected candle count
Inclusive range convention:

```python
def expected_candle_count(start_ts: int, end_ts: int, timeframe_seconds: int) -> int:
    return ((end_ts - start_ts) // timeframe_seconds) + 1
```

---

## Provider Adapter Interface

Provider-specific code should still be isolated behind an adapter.

```python
from typing import Protocol

class CandleProvider(Protocol):
    async def fetch_candles(
        self,
        symbol: str,
        start_ts: int,
        end_ts: int,
        timeframe_seconds: int,
        limit: int | None = None,
    ) -> list[Candle]:
        ...
```

Provider responsibilities and non-responsibilities remain unchanged.

---

## Simulated Provider / Backfill Validation Harness

The simulated local `aiohttp` candle server remains a good fit and should remain part of the architecture. The only meaningful spec change is in how outcomes are persisted and validated.

The backfill system should be able to run a job against the simulated provider and then assert outcomes such as:

- expected candle count in DuckDB
- missing candle count after first pass
- number of retry tasks created
- final completeness after retries
- correct task state transitions
- correct handling of empty or failing responses

This means the simulated provider is still an integration-test component for the full pipeline, not just a unit-test fixture.

---

## Chunk Planning

Initial backfill requests should still be split into request-sized chunks based on number of candles, not raw seconds.

```python
def plan_initial_ranges(
    aligned_start: int,
    aligned_end: int,
    timeframe_seconds: int,
    max_candles_per_request: int,
) -> list[TimeRange]:
    ranges: list[TimeRange] = []
    span = (max_candles_per_request - 1) * timeframe_seconds
    current = aligned_start

    while current <= aligned_end:
        chunk_end = min(current + span, aligned_end)
        ranges.append(TimeRange(start_ts=current, end_ts=chunk_end))
        current = chunk_end + timeframe_seconds

    return ranges
```

---

## Storage Layer Design

The storage layer should encapsulate all direct SQL usage, but with DuckDB-specific connection handling.

### Async integration requirement

Even though DuckDB does not provide the same concurrency model as PostgreSQL, the storage layer must not expose blocking behavior to the rest of the application. The module is expected to run inside a DearCyGui application using `asyncio`, so storage calls must be wrapped behind async methods that yield control back to the event loop while synchronous DuckDB work is performed.

### Why this is different from asyncpg

This distinction should be explicit in the design.

With PostgreSQL plus `asyncpg`, the database is a separate server process and Python is usually awaiting network I/O to that server. That fits naturally into `asyncio` because the driver can suspend on socket activity while the event loop keeps running other tasks.

DuckDB is different because it is embedded and runs in-process. A query is not primarily waiting on a remote server over a non-blocking socket. It is usually doing local CPU work and file I/O inside the same application process. From the event loop's point of view, a normal DuckDB `execute(...)` call is therefore blocking work.

As a result, an "async DuckDB adapter" usually means one of these:

- an async facade over synchronous DuckDB calls executed in a background thread
- executor-based offloading of blocking DuckDB work
- a wrapper that exposes `await` methods while still relying on serialized in-process execution underneath

That is still useful, but it is not the same as the client-server async model of `asyncpg`. For this backfill module, the design should therefore assume that DuckDB remains fundamentally blocking underneath and should explicitly offload and coordinate those calls.

### Suggested functions

```python
def connect_duckdb(database_path: str):
    ...

async def initialize_schema(connection) -> None:
    ...

async def insert_candles(connection, candles: list[Candle]) -> int:
    ...

async def create_backfill_job(connection, config: BackfillConfig, aligned_start: int, aligned_end: int) -> int:
    ...

async def enqueue_backfill_tasks(connection, job_id: int, config: BackfillConfig, ranges: list[TimeRange], task_type: str) -> int:
    ...

async def select_pending_tasks(connection, job_id: int | None = None) -> list[dict]:
    ...

async def mark_task_running(connection, task_id: int, worker_id: str) -> None:
    ...

async def update_backfill_job_status(connection, job_id: int, status: str) -> None:
    ...
```

### Important implementation note

DuckDB's Python driver is synchronous. In an async backfill runner, database calls should therefore be wrapped with `asyncio.to_thread(...)` or an equivalent single-writer worker pattern so that the event loop is not blocked by SQL execution.

This is a hard requirement, not merely an optimization. The design should assume that long-running inserts, validation queries, retry-task creation, and summary queries may happen while the surrounding GUI application continues rendering and servicing input.

Acceptable implementation patterns include:

- an async storage facade whose methods delegate DuckDB work through `asyncio.to_thread(...)`
- a dedicated single database worker thread receiving work from async callers
- a single writer coroutine that forwards all blocking DB work to one background thread

Unacceptable behavior for this spec:

- calling blocking DuckDB queries directly from async coroutines on the main event-loop thread
- treating "single-threaded database access" as permission to stall the host GUI loop

### Insert policy
Use idempotent inserts:

```sql
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
ON CONFLICT (provider, market_type, symbol, timeframe_seconds, timestamp) DO NOTHING;
```

---

## Validation Strategy

Validation should remain database-driven.

### Recommended approach
- Store all received candles in DuckDB.
- Ask DuckDB which expected timestamps are missing.
- Ask DuckDB to compress missing timestamps into contiguous ranges.
- Let Python create retry tasks from the returned gap rows.

### Thin Python validation layer
The Python validation layer should ideally do little more than:

- run parameterized SQL queries
- map rows into `GapRange` or summary objects
- make decisions about retries based on returned rows

This keeps DataFrame usage minimal and avoids heavy Python-side validation.

---

## SQL Drafts for Validation and Queue Operations

DuckDB can support the validation parts of the original SQL model quite well, but task claiming should be changed.

### 1. Missing timestamp detection

```sql
SELECT expected.ts AS missing_timestamp
FROM generate_series(?, ?, ?) AS expected(ts)
LEFT JOIN candles c
  ON c.timestamp = expected.ts
 AND c.provider = ?
 AND c.market_type = ?
 AND c.symbol = ?
 AND c.timeframe_seconds = ?
WHERE c.timestamp IS NULL
ORDER BY expected.ts;
```

Parameters:
1. aligned_start
2. aligned_end
3. timeframe_seconds
4. provider
5. market_type
6. symbol
7. timeframe_seconds

### 2. Contiguous gap detection

```sql
WITH missing AS (
    SELECT expected.ts AS ts
    FROM generate_series(?, ?, ?) AS expected(ts)
    LEFT JOIN candles c
      ON c.timestamp = expected.ts
     AND c.provider = ?
     AND c.market_type = ?
     AND c.symbol = ?
     AND c.timeframe_seconds = ?
    WHERE c.timestamp IS NULL
),
numbered AS (
    SELECT
        ts,
        ts - (ROW_NUMBER() OVER (ORDER BY ts) * ?) AS grp
    FROM missing
)
SELECT
    MIN(ts) AS gap_start,
    MAX(ts) AS gap_end,
    COUNT(*) AS candle_count
FROM numbered
GROUP BY grp
ORDER BY gap_start;
```

Parameters:
1. aligned_start
2. aligned_end
3. timeframe_seconds
4. provider
5. market_type
6. symbol
7. timeframe_seconds
8. timeframe_seconds

### 3. Job progress summary

```sql
WITH job AS (
    SELECT *
    FROM backfill_jobs
    WHERE job_id = ?
),
expected AS (
    SELECT CAST(((aligned_end - aligned_start) / timeframe_seconds + 1) AS BIGINT) AS expected_candles
    FROM job
),
stored AS (
    SELECT COUNT(*) AS stored_candles
    FROM candles c
    JOIN job j
      ON c.provider = j.provider
     AND c.market_type = j.market_type
     AND c.symbol = j.symbol
     AND c.timeframe_seconds = j.timeframe_seconds
    WHERE c.timestamp BETWEEN j.aligned_start AND j.aligned_end
),
missing AS (
    SELECT expected.ts
    FROM job j,
         generate_series(j.aligned_start, j.aligned_end, j.timeframe_seconds) AS expected(ts)
    LEFT JOIN candles c
      ON c.timestamp = expected.ts
     AND c.provider = j.provider
     AND c.market_type = j.market_type
     AND c.symbol = j.symbol
     AND c.timeframe_seconds = j.timeframe_seconds
    WHERE c.timestamp IS NULL
),
tasks AS (
    SELECT
        COUNT(*) FILTER (WHERE status = 'pending') AS pending_tasks,
        COUNT(*) FILTER (WHERE status = 'running') AS running_tasks,
        COUNT(*) FILTER (WHERE status = 'completed') AS completed_tasks,
        COUNT(*) FILTER (WHERE status = 'failed') AS failed_tasks
    FROM backfill_tasks
    WHERE job_id = ?
)
SELECT
    j.job_id,
    j.status,
    j.provider,
    j.market_type,
    j.symbol,
    j.timeframe_seconds,
    j.aligned_start,
    j.aligned_end,
    e.expected_candles,
    s.stored_candles,
    COUNT(m.ts) AS missing_candles,
    t.pending_tasks,
    t.running_tasks,
    t.completed_tasks,
    t.failed_tasks
FROM job j
CROSS JOIN expected e
CROSS JOIN stored s
CROSS JOIN tasks t
LEFT JOIN missing m ON TRUE
GROUP BY
    j.job_id,
    j.status,
    j.provider,
    j.market_type,
    j.symbol,
    j.timeframe_seconds,
    j.aligned_start,
    j.aligned_end,
    e.expected_candles,
    s.stored_candles,
    t.pending_tasks,
    t.running_tasks,
    t.completed_tasks,
    t.failed_tasks;
```

Parameters:
1. job_id
2. job_id

### 4. Task selection for Python-owned dispatch

Instead of safe concurrent claim SQL using `FOR UPDATE SKIP LOCKED`, v1 should use a simpler query to fetch pending tasks, and Python should decide which one to run next.

```sql
SELECT
    task_id,
    job_id,
    task_type,
    provider,
    market_type,
    symbol,
    timeframe_seconds,
    range_start,
    range_end,
    priority,
    retry_count,
    max_retries
FROM backfill_tasks
WHERE status = 'pending'
  AND retry_count <= max_retries
ORDER BY priority ASC, created_at ASC, task_id ASC;
```

When a task is chosen by the runner, Python should immediately mark it `running` with a separate update statement.

```sql
UPDATE backfill_tasks
SET
    status = 'running',
    claimed_by = ?,
    claimed_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
WHERE task_id = ?;
```

This is appropriate only because v1 assumes one owning process. If you later want true multi-process workers, the spec should move back toward PostgreSQL or another external coordinator.

---

## SQL Notes and Practical Guidance

### Why `generate_series` still works well
The missing timestamp and contiguous-gap parts of the original design map naturally onto DuckDB SQL and remain worth keeping in the database.

### Why task claiming changes
DuckDB is excellent for local analytics and durable state, but it is not the right foundation for Postgres-style multi-worker row locking. For a portable v1, Python should own dispatch and DuckDB should store task state.

### Why the database file still helps
Even without server-side queue semantics, a `.duckdb` file still gives durable resumability, inspectable job state, and SQL-based validation.

---

## Runner / Orchestration

The runner remains the main public entrypoint.

```python
async def run_backfill(
    config: BackfillConfig,
    provider: CandleProvider,
    connection,
) -> BackfillResult:
    ...
```

This async entrypoint is required even for the DuckDB version. The caller should be able to `await` the backfill from an already-running event loop without needing a separate synchronous wrapper around the whole job.

### Orchestration flow

```text
1. Validate config
2. Open or create the DuckDB file
3. Initialize schema
4. Align requested range
5. Create backfill job row
6. Plan initial ranges
7. Enqueue initial download tasks
8. Start async workers under one owning Python process
9. Workers request the next pending task from a Python-managed dispatcher
10. Each worker fetches candles and stores them in DuckDB
11. When initial tasks complete, run SQL gap detection
12. Enqueue retry tasks for each returned gap
13. Repeat validation until no gaps remain or retries are exhausted
14. Update final job status
15. Return BackfillResult
```

---

## Concurrency Model

For v1, use a bounded concurrency model with `asyncio.Semaphore`, Python-owned task dispatch, and DuckDB for durable state.

### Guidance
- Limit concurrent HTTP calls with a semaphore.
- Prefer a single DB writer coroutine or `asyncio.to_thread`-wrapped writes.
- Use one `aiohttp.ClientSession` per job or worker group.
- Let Python coordinate which task is active.
- Let DuckDB remain the durable task ledger and validation engine.
- Ensure every potentially slow database operation yields control away from the main event-loop thread.
- Assume the host loop may also be driving DearCyGui rendering and other unrelated async tasks.

### Example pattern

```python
async def worker_loop(worker_id: str, dispatcher, provider, connection, config):
    while True:
        task = await dispatcher.claim_next_task(worker_id)
        if task is None:
            break

        try:
            candles = await provider.fetch_candles(
                symbol=task.symbol,
                start_ts=task.range_start,
                end_ts=task.range_end,
                timeframe_seconds=task.timeframe_seconds,
                limit=config.max_candles_per_request,
            )
            await insert_candles(connection, candles)
            await mark_task_completed(connection, task.task_id)
        except Exception as exc:
            await mark_task_failed(connection, task.task_id, str(exc))
```

One straightforward dispatcher design is an in-memory priority queue populated from `backfill_tasks`, with every task-state transition persisted back into DuckDB.

---

## Error Handling Requirements

The module should explicitly handle the following:

- network timeouts
- connection errors
- malformed JSON
- HTTP non-200 responses
- provider returning empty data
- provider returning duplicate candles
- provider returning out-of-order candles
- provider returning off-grid candles
- DuckDB file open or transaction failures
- write contention caused by incorrect multi-writer usage
- cancellation during shutdown

### Behavior guidelines
- Fatal configuration errors should fail fast.
- Request-specific failures should be recorded in task state and retried if eligible.
- Empty responses should not be treated as success unless the range is genuinely expected to be empty.
- If the database file is locked by another process unexpectedly, fail clearly and preserve resumable state.

---

## Logging Recommendations

Log at least the following events:

- job creation
- DuckDB file path
- aligned requested range
- initial chunk scheduling
- task enqueueing
- task dispatch start and completion
- received row count
- inserted row count
- validation missing count
- retry task scheduling
- retry exhaustion
- final job summary

### Example final summary fields
- job id
- provider
- symbol
- timeframe
- aligned start and end
- expected candle count
- stored candle count
- retry attempt count
- unresolved gap count
- final status
- database file path

---

## Testing Strategy

The same simulated local test server remains useful, but the database test setup changes materially.

### Recommended simulation scenarios
1. perfect aligned response
2. truncated response
3. random missing middle candles
4. misaligned request with aligned output
5. empty response
6. duplicate candles
7. out-of-order candles
8. intermittent timeout
9. intermittent HTTP error
10. overlapping responses

### Storage-specific success criteria
- a test can create a temporary `.duckdb` file and initialize schema
- idempotent inserts do not create duplicate rows
- missing timestamp validation works from DuckDB SQL
- retry tasks are created only for missing ranges
- resumability works when reopening the same database file
- async backfill execution does not noticeably stall the host event loop during blocking DuckDB work

### Test structure changes from the PostgreSQL version
- replace live PostgreSQL integration tests with temp-file DuckDB integration tests
- remove external credential requirements
- verify SQL placeholders and type conversions against DuckDB semantics
- verify that async orchestration does not block the event loop excessively when using synchronous DuckDB calls

### Recommended event-loop integration test

Add a test that runs `run_backfill(...)` alongside a lightweight coroutine that increments a counter or heartbeat on a short interval. The heartbeat should continue advancing while DuckDB-backed storage operations are happening, demonstrating that the backfill module does not freeze the shared event loop.

---

## Implementation Milestones

The milestone sequence is similar to the PostgreSQL version, but some milestones change meaningfully.

### Milestone 0 - Freeze v1 scope
Goal: define what is explicitly in and out of scope for the first usable version.

Include in v1:
- one provider adapter at a time
- one symbol per backfill job
- one timeframe per backfill job
- DuckDB-backed jobs, tasks, and candle storage
- SQL-based validation in DuckDB
- simulated REST candle provider
- async workers in one Python process

Exclude from v1:
- GUI integration
- multiple providers in one orchestration run
- multi-symbol scheduling
- distributed workers across processes or machines
- database-level multi-worker task claiming
- advanced market calendar logic

Success criteria:
- v1 boundaries are written down and agreed on
- implementation work is protected from uncontrolled scope growth

### Milestone 1 - Schema and storage foundation
Goal: get the local database foundation working first.

Implement:
- `candles`
- `backfill_jobs`
- `backfill_tasks`
- essential indexes
- Python DuckDB connection helpers
- `create_backfill_job()`
- `enqueue_backfill_tasks()`
- `insert_candles()`

Success criteria:
- a job can be created in DuckDB
- tasks can be enqueued and inspected with SQL
- candles can be inserted idempotently
- duplicate candle inserts do not create duplicate rows

### Milestone 2 - Simulated provider
Goal: turn the test server into a reusable validation harness.

Implement:
- `test_server.py`
- aligned candle generation
- local `aiohttp` server context
- `GET /products/{product_id}/candles`
- `perfect` mode
- one partial mode such as `truncate_tail`
- deterministic seed handling where applicable

Success criteria:
- the local server can be started and stopped cleanly
- the endpoint returns deterministic candle arrays
- both full and partial responses can be requested intentionally

### Milestone 3 - Basic provider adapter and one-shot ingestion
Goal: fetch one range from the simulated provider and store it.

Implement:
- one provider adapter for the simulated server
- one-shot fetch for a requested time range
- response normalization into `Candle` objects
- insert into DuckDB

Success criteria:
- one requested range can be downloaded successfully
- rows land in DuckDB with correct keys and timestamps
- perfect-mode requests produce the expected candle count

### Milestone 4 - SQL validation layer
Goal: prove completeness checks work in DuckDB.

Implement:
- missing timestamp query
- contiguous gap detection query
- simple job summary query
- lightweight Python wrappers over those SQL queries

Success criteria:
- perfect mode returns zero missing timestamps
- truncated mode returns the expected missing range
- contiguous gap detection identifies the correct retry interval
- summary query reports expected, stored, and missing counts correctly

### Milestone 5 - Python-owned task dispatcher
Goal: introduce the single-process worker model that replaces Postgres row locking.

Implement:
- pending-task selection query
- in-memory dispatcher or coordinator
- task state updates (`pending`, `running`, `completed`, `failed`)
- async worker coroutine loop
- per-task error handling

Success criteria:
- multiple async workers in one process do not duplicate task execution
- task state transitions are visible in DuckDB
- successful tasks complete cleanly
- failing tasks move to a failure state correctly

### Milestone 6 - Initial backfill job runner
Goal: run an entire initial backfill pass across planned chunks.

Implement:
- range normalization
- chunk planning by candle count
- initial task enqueueing
- worker startup for all initial tasks
- end-of-pass summary reporting

Success criteria:
- a requested range is split into correct initial chunks
- all initial tasks are attempted
- candles from multiple chunks land in DuckDB correctly
- job summary is accurate after the first full pass

### Milestone 7 - Retry engine v1
Goal: repair missing ranges after the first pass.

Implement:
- detect gaps after the initial pass
- create retry tasks only for missing contiguous ranges
- run workers on retry tasks
- stop when complete or retry limits are exhausted
- final job status update (`complete`, `partial`, `failed`)

Success criteria:
- `truncate_tail` can be repaired by targeted retries
- `drop_middle_block` can be repaired by targeted retries
- retry tasks are created only for missing ranges
- jobs end in the correct final state

### Milestone 8 - Robustness and failure modes
Goal: validate behavior under more difficult provider responses.

Implement more simulated modes such as:
- `duplicate_rows`
- `out_of_order`
- `empty`
- `timeout`
- `http_500`
- `partial_then_success`

Success criteria:
- duplicate rows remain harmless due to idempotent inserts
- out-of-order responses still validate correctly after insert
- timeout and HTTP failures are reflected in task state correctly
- `partial_then_success` converges to completeness after retries

### Milestone 9 - GUI readiness and polish
Goal: make the system easy to embed into a future asyncio GUI.

Implement:
- lightweight status and progress query helpers
- cancellation and shutdown handling
- structured logging improvements
- cleaner progress summaries for display

Success criteria:
- background work can run without blocking the event loop
- progress can be queried from DuckDB without in-memory coupling
- jobs and workers can shut down cleanly
- the system is ready for integration into a GUI shell later

### Recommended first usable stop point
A strong first usable version of the system is Milestones 1 through 7.

---

## Suggested OpenSpec Change Groupings

Because this module is intended to be implemented through OpenSpec changes, the milestones above should be grouped into change requests that are coherent, reviewable, and independently testable. The goal is to avoid changes that are either so small that they produce process overhead without meaningful behavior, or so large that design review becomes vague and risky.

### Grouping principles

- One OpenSpec change should usually correspond to one usable implementation slice.
- Each change should end with behavior that can be demonstrated or tested.
- Storage-model changes and orchestration-model changes should stay explicit rather than being hidden inside one giant proposal.
- Changes that introduce new operational risk should be isolated enough that rollback or redesign is still practical.

### Recommended change groups

#### Change 1 - Freeze scope and storage foundation

Group together:

- Milestone 0
- Milestone 1

Why this grouping makes sense:

- The scope boundary and the storage schema are tightly coupled.
- This is the point where the project commits to DuckDB as the portable local backend.
- Reviewers can validate the data model, persistence assumptions, and single-process boundary before higher-level orchestration is added.

Expected outcome:

- agreed v1 scope
- schema and indexes in place
- connection helpers and basic insert or enqueue primitives working

#### Change 2 - Simulated provider and one-shot ingestion

Group together:

- Milestone 2
- Milestone 3

Why this grouping makes sense:

- These milestones create the first end-to-end ingestion path.
- The simulated provider is most valuable once it is exercised through the real adapter and storage path.
- This gives the project its first concrete demonstration that candles can be fetched, normalized, and stored correctly.

Expected outcome:

- deterministic local provider harness
- one provider adapter
- one-shot fetch and insert path validated against DuckDB

#### Change 3 - SQL validation and Python-owned task dispatch

Group together:

- Milestone 4
- Milestone 5

Why this grouping makes sense:

- Validation and dispatch are the core replacements for the old PostgreSQL worker-claim model.
- Gap detection without task dispatch is analytically useful but not yet operationally meaningful.
- Dispatch without validation leaves the retry engine underdefined.

Expected outcome:

- missing timestamp and gap queries working
- persisted task state transitions working
- in-memory dispatcher or coordinator running inside one process

#### Change 4 - Initial runner and retry engine v1

Group together:

- Milestone 6
- Milestone 7

Why this grouping makes sense:

- These milestones together create the first truly usable backfill job.
- An initial runner without targeted retries is incomplete for the stated purpose of the module.
- A retry engine without a real runner has nowhere meaningful to attach.

Expected outcome:

- planned chunk execution across a real job
- targeted retry scheduling from detected gaps
- final job statuses such as `complete`, `partial`, and `failed`

#### Change 5 - Failure-mode hardening

Group together:

- Milestone 8

Why this grouping makes sense:

- Failure-mode coverage is important, but it is best reviewed after the happy-path and retry architecture already exist.
- This change has a distinct goal: prove the design is resilient under bad upstream behavior.

Expected outcome:

- richer simulated failure modes
- validated behavior for duplicates, out-of-order rows, timeouts, and intermittent partial responses

#### Change 6 - GUI readiness and operational polish

Group together:

- Milestone 9

Why this grouping makes sense:

- GUI-readiness is important, but it is mostly polish and integration hardening rather than core backfill semantics.
- Keeping it separate makes it easier to review event-loop behavior, cancellation, and status-query ergonomics on their own terms.

Expected outcome:

- progress and status helpers suitable for a DearCyGui host
- cleaner shutdown and cancellation behavior
- better logging and user-facing summaries

### Recommended first implementation sequence in OpenSpec terms

If the goal is to move steadily toward a usable version without oversized proposals, the most sensible OpenSpec sequence is:

1. Change 1: scope plus storage foundation
2. Change 2: provider harness plus one-shot ingestion
3. Change 3: validation plus task dispatch
4. Change 4: full runner plus retry engine
5. Change 5: failure-mode hardening
6. Change 6: GUI readiness and polish

### What should not be grouped together

These combinations would likely make review harder than necessary:

- Milestones 1 through 7 in one giant change request
- GUI-readiness work mixed into the first storage or ingestion proposal
- failure-mode hardening mixed into the first end-to-end runner proposal
- storage-foundation work bundled together with final retry semantics and GUI integration

Those larger bundles would make it harder to reason about whether a proposal is changing the data model, the orchestration model, or host-application integration behavior.

---

## Suggested Implementation Order

To keep development manageable in VS Code, implement in this order:

1. Freeze v1 scope.
2. Create DuckDB schema and indexes.
3. Create dataclasses for config, candle, range, gap, task, and result.
4. Implement alignment and chunk planning helpers.
5. Implement one provider adapter using the local `aiohttp` test server.
6. Implement the simulated provider and validation harness modes.
7. Implement `insert_candles()` and SQL query wrappers.
8. Implement the Python-owned dispatcher and task status update functions.
9. Implement `run_backfill()` with initial tasks only.
10. Add SQL-based gap detection and retry task creation.
11. Add final summary query and GUI-friendly status reads.
12. Add richer test-server failure modes and deterministic seeds.

---

## Practical Notes for This Repository

This repository already uses DuckDB successfully for local cache-oriented workflows. That means the DuckDB variant is aligned with existing project patterns, but the backfill spec should still keep a clear distinction between:

- cache-style read-through helpers
- durable backfill job state
- SQL validation of completeness

Because the intended host is a DearCyGui application using `asyncio`, the implementation should treat event-loop responsiveness as a first-class requirement alongside portability.

For the backfiller, the DuckDB file should act as the durable local job store rather than only an opportunistic query cache.

---

## Minimal v1 Public API

```python
async def run_backfill(config: BackfillConfig, provider: CandleProvider, connection) -> BackfillResult:
    """Run a historical backfill job and return the final completeness summary."""
```

---

## Future Extensions

Possible future improvements after v1:

- multi-symbol job orchestration
- market-calendar-aware stock gap policies
- adaptive chunk sizing
- range expansion retries
- job resumption across process restarts
- richer metrics and dashboards
- optional export or sync from DuckDB into PostgreSQL for centralized storage
- automated integration tests against the simulated provider
- live incremental updater using the same storage model

If future requirements include multiple machines or multiple concurrent worker processes claiming shared tasks, the spec should explicitly reintroduce a server-grade coordinator rather than stretching DuckDB beyond its intended portability-focused role.

---

## Summary

The recommended DuckDB architecture is:

- async Python for fetching and orchestration
- DuckDB for portable persistent storage and primary validation
- provider adapters for source-specific logic
- a simulated local REST candle provider for controlled failure-mode testing
- SQL `generate_series` for missing timestamp detection
- SQL window functions for contiguous gap detection
- SQL summary queries for GUI-friendly progress reporting
- Python-owned task dispatch instead of Postgres row locking

This keeps the module understandable, testable, portable, and consistent with the local-machine workflow you are already using in this repository.
