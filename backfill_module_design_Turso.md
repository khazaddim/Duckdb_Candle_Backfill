# Python-Oriented Design: Historical Candle Backfill Module (Local Turso / pyturso Variant)

## Purpose

This document specifies a database-first Python design for a historical candle backfill module for crypto and stock market data using the local Turso Database engine through `pyturso`. The module downloads OHLCV candles asynchronously, stores them in a local Turso database file, validates completeness against the expected timestamp grid, and retries only missing ranges until the requested backfill is complete or retry limits are reached.

The design is intended to be practical for local development in VS Code and consistent with an `aiohttp` + `pyturso` workflow that is portable across developer machines.

Because this module is expected to run inside a DearCyGui application that already owns an `asyncio` event loop, the backfill API must remain async from the caller's point of view and must not block the event loop while performing database work.

---

## Why a Local Turso Variant

This variant targets local `pyturso`, which is built on the Turso Database engine and exposed through a Python `sqlite3`-compatible API.

Compared with the DuckDB variant, local Turso changes the tradeoffs in these ways:

- it keeps the backfill state in a local `.db` file instead of a DuckDB file
- it remains embedded and local-first rather than introducing a server dependency
- it preserves a SQL-first validation model
- it supports concurrent local writers through MVCC when explicitly enabled
- it offers an asyncio-friendly Python API via `turso.aio`

It also imposes constraints that should be explicit in the spec:

- default local mode still allows only one writer at a time unless MVCC is enabled
- concurrent write transactions use optimistic conflict detection and retry, not PostgreSQL row-lock claiming
- worker coordination should assume one owning Python process on Windows
- multi-process access is experimental and documented as ineffective on Windows
- v1 should target local `pyturso` only, not Turso Cloud, embedded replicas, `libsql`, or sync

The practical outcome is important: local Turso gets closer to PostgreSQL-style concurrent workers than DuckDB does, but it does not restore PostgreSQL's exact `FOR UPDATE SKIP LOCKED` model. The correct mental model is optimistic multi-writer concurrency with retry on conflict.

---

## Design Goals

### Functional goals
- Download OHLCV candles for a symbol across a requested historical time range.
- Normalize misaligned requested times to valid candle boundaries.
- Insert candles into Turso using idempotent writes.
- Detect missing timestamps after initial downloads.
- Compress missing timestamps into contiguous retry ranges.
- Retry only those missing ranges.
- Produce a final summary describing completeness and unresolved gaps.

### Non-functional goals
- Keep the backfill database portable across Windows laptops and other developer machines.
- Preserve SQL-first validation instead of pushing completeness checks into large Python DataFrames.
- Support resumable and repeatable local backfills.
- Remain safe to run inside an already-running `asyncio` application, including DearCyGui-based GUI applications.
- Expose an async public API through `turso.aio` so storage work does not block the host loop.
- Allow multiple local worker connections to write concurrently when MVCC is enabled.
- Keep provider-specific logic isolated from the core retry engine.
- Keep the first implementation small enough to build incrementally.

---

## Recommended Module Layout

```text
Macro_Ideas/
  docs/
    backfill_module_design.md
    backfill_module_design_duckdb.md
    backfill_module_design_turso.md
  market_data/
    __init__.py
    backfill/
      __init__.py
      config.py
      models.py
      providers.py
      planner.py
      storage_turso.py
      validator.py
      retry_engine.py
      runner.py
      test_server.py
      sql/
        turso_schema.sql
        turso_queries.sql
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
- `storage_turso.py`
  - Turso connection management plus insert/query helpers
- `validator.py`
  - thin wrappers over validation queries plus light gap/result mapping
- `retry_engine.py`
  - retry scheduling and retry loop behavior
- `runner.py`
  - orchestration entrypoint for a backfill job
- `test_server.py`
  - simulated candle provider for validation and failure-mode testing
- `sql/turso_schema.sql`
  - DDL for tables and indexes
- `sql/turso_queries.sql`
  - validation, summary, and task update SQL

---

## Core Design Principles

### 1. Database-first ingestion
Candles should be written to Turso as soon as they are received. Validation should compare the expected timestamp grid against the database contents for the requested range.

### 2. SQL-first validation
Validation should primarily happen in the database, not in Pandas or large in-memory Python structures. Python should remain thin and focus on orchestration, async HTTP I/O, provider normalization, and translating SQL results into retry actions.

### 3. Canonical candle timestamp
Every candle timestamp represents the open time of the candle in Unix epoch seconds.

### 4. Strict timeframe alignment
All candle timestamps must be aligned to the timeframe grid. For a timeframe of `3600`, valid timestamps are exact hour boundaries.

### 5. Idempotent inserts
Repeated downloads must not create duplicate rows or corrupt previously stored data.

### 6. Retry missing ranges only
Retries should operate only on ranges proven to be missing from the database.

### 7. Optimistic multi-writer task execution
When MVCC is enabled, multiple worker connections may write concurrently. Conflicts are detected at commit time, so task claiming and task-state transitions must be designed around retryable optimistic updates rather than row-lock blocking.

### 8. Event-loop-safe async integration
The backfill module must integrate as an async component. It must be safe to run inside an existing `asyncio` loop without freezing GUI rendering, input handling, timers, or other application tasks.

### 9. One owning process on Windows for v1
Even though Turso documents experimental multi-process access on some Unix-like systems, that feature is documented as having no effect on Windows. v1 should therefore assume one owning Python process coordinates the backfill on Windows, even if that process uses multiple async workers and multiple local connections.

---

## Why Validation Should Primarily Happen in Turso

For this project, local Turso remains a better place than Python DataFrames for most validation tasks.

### Benefits
- Avoids building large expected timestamp arrays in Python.
- Keeps the local database file as the source of truth for job completeness.
- Makes validation logic queryable and inspectable with SQL.
- Supports resumability and crash recovery without running a separate server.
- Makes progress reporting easier for a future GUI workflow.
- Preserves portability with a single local database file.

### Validation tasks that belong in Turso
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
- retrying optimistic write conflicts
- GUI-facing orchestration and user interaction

The intended architecture is:
- Turso = local durable state plus validation source of truth
- Python = async orchestration, provider adapters, and worker coordination

---

## Key Architectural Changes from the PostgreSQL Version

The original PostgreSQL-oriented spec needs these concrete changes to fit local Turso:

1. Replace `asyncpg` pool usage with `turso.aio` connections.
2. Replace server-based connection strings with a local file path such as `market_data.db`.
3. Replace `JSONB` columns with `TEXT` storing serialized JSON, or JSON-oriented SQL functions where helpful.
4. Replace `BIGSERIAL` and PostgreSQL sequences with `INTEGER PRIMARY KEY AUTOINCREMENT`.
5. Keep `?` placeholders.
6. Replace `FOR UPDATE SKIP LOCKED` queue claiming with optimistic claim-and-retry logic.
7. Enable MVCC explicitly for concurrent local writers with `PRAGMA journal_mode = 'mvcc'`.
8. Require retry handling for write conflicts and busy errors.
9. Rewrite integration tests to create temporary local `.db` files instead of requiring a live PostgreSQL instance.
10. Keep the public API async, using `turso.aio` rather than wrapping a blocking embedded engine manually.

---

## Recommended Database Schema

Use the default schema for maximum portability and simplicity.

### Candles table

```sql
CREATE TABLE IF NOT EXISTS candles (
    provider TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    timestamp INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    fetched_at INTEGER NOT NULL DEFAULT (unixepoch()),
    raw_json TEXT,
    PRIMARY KEY (provider, market_type, symbol, timeframe_seconds, timestamp)
);
```

`raw_json` should default to `TEXT` for the most predictable SQLite-compatible behavior in Python.

### Backfill jobs table

```sql
CREATE TABLE IF NOT EXISTS backfill_jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    requested_start INTEGER NOT NULL,
    requested_end INTEGER NOT NULL,
    aligned_start INTEGER NOT NULL,
    aligned_end INTEGER NOT NULL,
    status TEXT NOT NULL,
    max_retries INTEGER NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
);
```

### Backfill tasks table

```sql
CREATE TABLE IF NOT EXISTS backfill_tasks (
    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    market_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe_seconds INTEGER NOT NULL,
    range_start INTEGER NOT NULL,
    range_end INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    claimed_by TEXT,
    claimed_at INTEGER,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
    FOREIGN KEY (job_id) REFERENCES backfill_jobs(job_id)
);
```

### Optional backfill attempts table

```sql
CREATE TABLE IF NOT EXISTS backfill_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    task_id INTEGER,
    range_start INTEGER NOT NULL,
    range_end INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    requested_candles INTEGER,
    received_candles INTEGER,
    missing_after_attempt INTEGER,
    error_message TEXT,
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    finished_at INTEGER,
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
    turso_path: Path
    max_candles_per_request: int = 300
    max_concurrent_requests: int = 5
    max_retries_per_gap: int = 3
    request_timeout_seconds: int = 30
    retry_backoff_seconds: float = 1.0
    split_large_gaps_threshold: int = 100
    store_raw_json: bool = False
    enable_mvcc: bool = True
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

These rules are unchanged from the PostgreSQL and DuckDB variants.

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

The simulated local `aiohttp` candle server remains a good fit and should remain part of the architecture.

The backfill system should be able to run a job against the simulated provider and then assert outcomes such as:

- expected candle count in Turso
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

The storage layer should encapsulate all direct SQL usage through local `turso.aio` connections.

### Async integration requirement

This variant should prefer `turso.aio`, which is designed to keep database work off the main event loop while still exposing an async API. That is materially better than the DuckDB variant, where async behavior had to be provided by hand around a synchronous driver.

### Why this is still not PostgreSQL

This distinction should remain explicit.

With PostgreSQL plus `asyncpg`, the database is a separate server and workers coordinate through server-side transaction and row-lock semantics.

With local Turso plus `pyturso`, the database remains embedded and local. Even though the async API is better and MVCC allows multiple local writers, contention is still resolved optimistically at commit time. If two writers modify the same data, one may receive a retryable conflict or busy error.

As a result, a Turso-based async adapter means:

- an async API backed by Turso's asyncio support
- one or more local connections inside the process
- optional MVCC-enabled concurrent writes
- retry logic around optimistic write conflicts

That is closer to PostgreSQL than DuckDB was, but it is still not a row-locking database server.

### Suggested functions

```python
async def connect_turso(database_path: str, *, enable_mvcc: bool = True):
    ...

async def initialize_schema(connection) -> None:
    ...

async def insert_candles(connection, candles: list[Candle]) -> int:
    ...

async def create_backfill_job(connection, config: BackfillConfig, aligned_start: int, aligned_end: int) -> int:
    ...

async def enqueue_backfill_tasks(connection, job_id: int, config: BackfillConfig, ranges: list[TimeRange], task_type: str) -> int:
    ...

async def claim_next_task(connection, worker_id: str, job_id: int | None = None):
    ...

async def mark_task_completed(connection, task_id: int) -> None:
    ...

async def mark_task_failed(connection, task_id: int, error_message: str) -> None:
    ...

async def update_backfill_job_status(connection, job_id: int, status: str) -> None:
    ...
```

### Important implementation note

Use `turso.aio` for the primary storage interface. Prefer one connection per worker or a small connection set rather than funneling all writes through one serialized writer, otherwise the main concurrency advantage of local Turso is lost.

When `enable_mvcc=True`, each connection should execute:

```sql
PRAGMA journal_mode = 'mvcc';
```

Transactions that are intended to participate in concurrent write execution should use:

```sql
BEGIN CONCURRENT;
```

If commit fails because of conflict or busy conditions, the transaction must roll back and retry.

### Acceptable implementation patterns

- `turso.aio` connections used directly from async code
- multiple worker connections with MVCC enabled
- optimistic claim-and-update transaction loops that retry on conflicts
- a single owning process with several concurrent local connections

### Unacceptable implementation patterns

- assuming default journal mode provides safe high-write concurrency without contention
- assuming PostgreSQL row-lock behavior exists when it does not
- depending on multi-process shared-file coordination on Windows for v1

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
- Store all received candles in Turso.
- Ask Turso which expected timestamps are missing.
- Ask Turso to compress missing timestamps into contiguous ranges.
- Let Python create retry tasks from the returned gap rows.

### Thin Python validation layer
The Python validation layer should ideally do little more than:

- run parameterized SQL queries
- map rows into `GapRange` or summary objects
- make decisions about retries based on returned rows

This keeps DataFrame usage minimal and avoids heavy Python-side validation.

---

## SQL Drafts for Validation and Queue Operations

Local Turso should support the validation parts of the original SQL model well, but queue claiming should be optimistic rather than lock-based.

### 1. Missing timestamp detection

```sql
SELECT expected.value AS missing_timestamp
FROM generate_series(?, ?, ?) AS expected
LEFT JOIN candles c
  ON c.timestamp = expected.value
 AND c.provider = ?
 AND c.market_type = ?
 AND c.symbol = ?
 AND c.timeframe_seconds = ?
WHERE c.timestamp IS NULL
ORDER BY expected.value;
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
    SELECT expected.value AS ts
    FROM generate_series(?, ?, ?) AS expected
    LEFT JOIN candles c
      ON c.timestamp = expected.value
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
    SELECT CAST(((aligned_end - aligned_start) / timeframe_seconds + 1) AS INTEGER) AS expected_candles
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
    SELECT expected.value AS ts
    FROM job j,
         generate_series(j.aligned_start, j.aligned_end, j.timeframe_seconds) AS expected
    LEFT JOIN candles c
      ON c.timestamp = expected.value
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

### 4. Task selection with optimistic claiming

Instead of `FOR UPDATE SKIP LOCKED`, workers should use an optimistic claim loop.

One simple pattern is:

1. start `BEGIN CONCURRENT`
2. select the best pending task candidate
3. attempt `UPDATE ... WHERE task_id = ? AND status = 'pending'`
4. if no row was updated, roll back and retry
5. if commit conflicts, roll back and retry

Candidate selection query:

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
ORDER BY priority ASC, created_at ASC, task_id ASC
LIMIT 1;
```

Claim attempt:

```sql
UPDATE backfill_tasks
SET
    status = 'running',
    claimed_by = ?,
    claimed_at = unixepoch(),
    updated_at = unixepoch()
WHERE task_id = ?
  AND status = 'pending';
```

This is not the same as PostgreSQL row locking, but with MVCC and retry loops it is enough for one-process, many-worker execution.

---

## SQL Notes and Practical Guidance

### Why `generate_series` still works well
The missing timestamp and contiguous-gap parts of the original design still map well onto Turso SQL.

### Why task claiming still changes
Local Turso provides concurrent writers, but not the PostgreSQL mental model of server-side row-lock dispatch. Queue claiming should therefore be designed as optimistic compare-and-claim logic.

### Why the local file still helps
Even without a server tier, a local `.db` file still gives durable resumability, inspectable job state, and SQL-based validation.

### Why multi-process is out of scope for v1
Turso documents experimental multi-process WAL support only on supported Unix-like platforms and states that on Windows the flag has no effect. Since this project is expected to run locally on Windows, v1 should not depend on cross-process shared-file coordination.

---

## Runner / Orchestration

The runner remains the main public entrypoint.

```python
async def run_backfill(
    config: BackfillConfig,
    provider: CandleProvider,
) -> BackfillResult:
    ...
```

This async entrypoint remains required. The caller should be able to `await` the backfill from an already-running event loop without wrapping the entire job in a synchronous shell.

### Host application integration

The primary target for this variant is a local Python GUI application that already owns the `asyncio` event loop.

That leads to these requirements:

- the backfill runner must be started with `await` or `asyncio.create_task(...)`, not `asyncio.run(...)`
- storage and network activity must remain non-blocking from the GUI loop's perspective
- progress should be queryable without tight in-memory coupling between the GUI layer and worker internals
- cancellation should propagate through normal async task cancellation paths

Recommended host pattern:

```python
backfill_task = asyncio.create_task(run_backfill(config, provider))

# GUI timer / coroutine can periodically query progress helpers
# without blocking rendering.
```

The GUI should treat the database as the durable source of truth for progress and should avoid depending on direct references to worker-local state.

### Orchestration flow

```text
1. Validate config
2. Open or create the local Turso database file
3. Initialize schema
4. Align requested range
5. Create backfill job row
6. Plan initial ranges
7. Enqueue initial download tasks
8. Start async workers inside one owning Python process
9. Each worker uses its own async connection and optimistic task-claim loop
10. Each worker fetches candles and stores them in Turso
11. When initial tasks complete, run SQL gap detection
12. Enqueue retry tasks for each returned gap
13. Repeat validation until no gaps remain or retries are exhausted
14. Update final job status
15. Return BackfillResult
```

---

## Concurrency Model

For v1, use a bounded concurrency model with `asyncio.Semaphore`, multiple `turso.aio` connections, and MVCC-enabled optimistic writes.

### Guidance
- Limit concurrent HTTP calls with a semaphore.
- Prefer one database connection per worker or a small shared pool.
- Enable MVCC when concurrent write throughput matters.
- Wrap claim, complete, fail, and retry-task creation in transaction retry loops.
- Use one `aiohttp.ClientSession` per job or worker group.
- Assume the host loop may also be driving DearCyGui rendering and other unrelated async tasks.
- Keep execution inside one Python process on Windows.
- Do not introduce nested event-loop control such as calling `asyncio.run(...)` from inside the GUI host.

### Example pattern

```python
async def worker_loop(worker_id: str, provider, connection_factory, config):
    conn = await connection_factory()
    try:
        while True:
            task = await claim_next_task(conn, worker_id)
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
                await insert_candles(conn, candles)
                await mark_task_completed(conn, task.task_id)
            except Exception as exc:
                await mark_task_failed(conn, task.task_id, str(exc))
    finally:
        await conn.close()
```

The key difference from the DuckDB design is that the workers do not need to funnel all writes through one dedicated writer. The key difference from PostgreSQL is that queue coordination is still optimistic rather than row-lock driven.

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
- Turso file open or transaction failures
- retryable MVCC conflicts or busy errors during claims and writes
- cancellation during shutdown

### Behavior guidelines
- Fatal configuration errors should fail fast.
- Request-specific failures should be recorded in task state and retried if eligible.
- Empty responses should not be treated as success unless the range is genuinely expected to be empty.
- Retryable write conflicts should be retried with bounded backoff.
- Non-retryable storage errors should fail clearly and preserve resumable state.

---

## Logging Recommendations

Log at least the following events:

- job creation
- Turso file path
- aligned requested range
- initial chunk scheduling
- task enqueueing
- task dispatch start and completion
- received row count
- inserted row count
- validation missing count
- retry task scheduling
- MVCC conflict retries
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
- a test can create a temporary local `.db` file and initialize schema
- idempotent inserts do not create duplicate rows
- missing timestamp validation works from Turso SQL
- retry tasks are created only for missing ranges
- resumability works when reopening the same database file
- async backfill execution does not noticeably stall the host event loop
- concurrent local workers can claim and complete tasks without duplicate execution
- MVCC conflicts are retried and converge successfully in contention-heavy tests

### Test structure changes from the PostgreSQL version
- replace live PostgreSQL integration tests with temp-file Turso integration tests
- remove external credential requirements
- verify SQL placeholders and type conversions against SQLite-compatible semantics
- verify optimistic task claiming under concurrent workers
- verify that async orchestration does not block the event loop when using `turso.aio`

### Recommended event-loop integration test

Add a test that runs `run_backfill(...)` alongside a lightweight coroutine that increments a counter or heartbeat on a short interval. The heartbeat should continue advancing while Turso-backed storage operations are happening, demonstrating that the backfill module does not freeze the shared event loop.

### Recommended contention test

Add a test that starts multiple workers against a task set with MVCC enabled and verifies:

- every task is claimed exactly once
- total completed tasks equals enqueued tasks
- no task is left permanently stuck because of retryable conflicts

---

## Implementation Milestones

The milestone sequence is similar to the DuckDB version, but the concurrency milestones change meaningfully.

### Milestone 0 - Freeze v1 scope
Goal: define what is explicitly in and out of scope for the first usable version.

Include in v1:
- one provider adapter at a time
- one symbol per backfill job
- one timeframe per backfill job
- local Turso-backed jobs, tasks, and candle storage
- SQL-based validation in Turso
- simulated REST candle provider
- async workers in one Python process
- MVCC-enabled concurrent local writers

Exclude from v1:
- GUI integration
- multiple providers in one orchestration run
- multi-symbol scheduling
- cross-process shared-file coordination on Windows
- Turso Cloud, embedded replicas, and sync
- PostgreSQL-style row-lock claiming semantics
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
- Python `turso.aio` connection helpers
- optional MVCC initialization
- `create_backfill_job()`
- `enqueue_backfill_tasks()`
- `insert_candles()`

Success criteria:
- a job can be created in Turso
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
- insert into Turso

Success criteria:
- one requested range can be downloaded successfully
- rows land in Turso with correct keys and timestamps
- perfect-mode requests produce the expected candle count

### Milestone 4 - SQL validation layer
Goal: prove completeness checks work in Turso.

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

### Milestone 5 - Optimistic task dispatcher
Goal: introduce the multi-worker local dispatch model.

Implement:
- pending-task selection query
- optimistic task claim helper with retry
- task state updates (`pending`, `running`, `completed`, `failed`)
- async worker coroutine loop
- per-task error handling
- conflict classification and bounded retry behavior

Success criteria:
- multiple async workers in one process do not duplicate task execution
- task state transitions are visible in Turso
- successful tasks complete cleanly
- conflicting claim attempts converge correctly
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
- candles from multiple chunks land in Turso correctly
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
- a forced-conflict local concurrency mode for storage tests

Success criteria:
- duplicate rows remain harmless due to idempotent inserts
- out-of-order responses still validate correctly after insert
- timeout and HTTP failures are reflected in task state correctly
- `partial_then_success` converges to completeness after retries
- forced write conflicts are retried without corrupting queue state

### Milestone 9 - GUI readiness and polish
Goal: make the system easy to embed into a future asyncio GUI.

Implement:
- lightweight status and progress query helpers
- cancellation and shutdown handling
- structured logging improvements
- cleaner progress summaries for display

Success criteria:
- background work can run without blocking the event loop
- progress can be queried from Turso without in-memory coupling
- jobs and workers can shut down cleanly
- the system is ready for integration into a GUI shell later

### Recommended first usable stop point
A strong first usable version of the system is Milestones 1 through 7.

---

## Suggested OpenSpec Change Groupings

Because this module is intended to be implemented through OpenSpec changes, the milestones above should be grouped into change requests that are coherent, reviewable, and independently testable.

### Grouping principles

- One OpenSpec change should usually correspond to one usable implementation slice.
- Each change should end with behavior that can be demonstrated or tested.
- Storage-model changes and orchestration-model changes should stay explicit.
- Changes that introduce new operational risk should be isolated enough that rollback or redesign is still practical.

### Recommended change groups

#### Change 1 - Freeze scope and storage foundation

Group together:

- Milestone 0
- Milestone 1

Why this grouping makes sense:

- The scope boundary and the storage schema are tightly coupled.
- This is the point where the project commits to local Turso as the backend.
- Reviewers can validate the data model, MVCC assumptions, and one-process-on-Windows boundary before higher-level orchestration is added.

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

Expected outcome:

- deterministic local provider harness
- one provider adapter
- one-shot fetch and insert path validated against Turso

#### Change 3 - SQL validation and optimistic task dispatch

Group together:

- Milestone 4
- Milestone 5

Why this grouping makes sense:

- Validation and optimistic task dispatch are the core of the Turso concurrency model for this project.
- Gap detection without dispatch is analytically useful but not yet operationally meaningful.
- Dispatch without validation leaves the retry engine underdefined.

Expected outcome:

- missing timestamp and gap queries working
- persisted task state transitions working
- multi-worker optimistic dispatch running inside one process

#### Change 4 - Initial runner and retry engine v1

Group together:

- Milestone 6
- Milestone 7

Why this grouping makes sense:

- These milestones together create the first truly usable backfill job.
- An initial runner without targeted retries is incomplete for the stated purpose of the module.

Expected outcome:

- planned chunk execution across a real job
- targeted retry scheduling from detected gaps
- final job statuses such as `complete`, `partial`, and `failed`

#### Change 5 - Failure-mode hardening

Group together:

- Milestone 8

Why this grouping makes sense:

- Failure-mode coverage is important, but it is best reviewed after the happy-path and retry architecture already exist.

Expected outcome:

- richer simulated failure modes
- validated behavior for duplicates, out-of-order rows, timeouts, intermittent partial responses, and write conflicts

#### Change 6 - GUI readiness and operational polish

Group together:

- Milestone 9

Why this grouping makes sense:

- GUI-readiness is mostly polish and integration hardening rather than core backfill semantics.

Expected outcome:

- progress and status helpers suitable for a DearCyGui host
- cleaner shutdown and cancellation behavior
- better logging and user-facing summaries

---

## Suggested Implementation Order

To keep development manageable in VS Code, implement in this order:

1. Freeze v1 scope.
2. Create Turso schema and indexes.
3. Create dataclasses for config, candle, range, gap, task, and result.
4. Implement alignment and chunk planning helpers.
5. Implement one provider adapter using the local `aiohttp` test server.
6. Implement the simulated provider and validation harness modes.
7. Implement `insert_candles()` and SQL query wrappers.
8. Implement the optimistic dispatcher and task status update functions.
9. Implement `run_backfill()` with initial tasks only.
10. Add SQL-based gap detection and retry task creation.
11. Add final summary query and GUI-friendly status reads.
12. Add contention-heavy worker tests and deterministic conflict retries.

---

## Practical Notes for This Repository

This repository already uses DuckDB successfully for local cache-oriented workflows. The Turso variant would be a deliberate shift in storage engine and concurrency model, not just a path rename.

The most important architecture change is this:

- DuckDB required serialized off-loop access because the Python driver was synchronous.
- Local Turso offers an async Python API and optional MVCC for concurrent local writers.
- Even so, queue coordination should remain optimistic and retry-based rather than pretending PostgreSQL row locks exist.

Because the intended host is a DearCyGui application using `asyncio`, the implementation should treat event-loop responsiveness as a first-class requirement alongside portability.

For the backfiller, the local Turso file should act as the durable local job store rather than only an opportunistic query cache.

---

## Minimal v1 Public API

```python
async def run_backfill(config: BackfillConfig, provider: CandleProvider) -> BackfillResult:
    """Run a historical backfill job and return the final completeness summary."""
```

---

## Future Extensions

Possible future improvements after v1:

- multi-symbol job orchestration
- adaptive chunk sizing
- range expansion retries
- job resumption across process restarts
- richer metrics and dashboards
- optional export or sync from Turso into another system
- automated integration tests against the simulated provider
- live incremental updater using the same storage model
- Unix-only investigation of experimental multi-process WAL when Windows is no longer a target constraint

If future requirements include multiple machines or multiple worker processes coordinating across a shared remote backend, the design should add a separate Turso Cloud or server-backed variant rather than stretching the local Windows-first assumptions in this document.

---

## Summary

The recommended local Turso architecture is:

- async Python for fetching and orchestration
- local `pyturso` and `turso.aio` for durable persistent storage
- MVCC-enabled concurrent local writers when beneficial
- provider adapters for source-specific logic
- a simulated local REST candle provider for controlled failure-mode testing
- SQL `generate_series` for missing timestamp detection
- SQL window functions for contiguous gap detection
- SQL summary queries for GUI-friendly progress reporting
- optimistic task claiming with retry instead of PostgreSQL row locking

This keeps the module understandable, testable, portable, and closer to a real multi-worker local design than the DuckDB variant, without claiming PostgreSQL semantics that local Turso does not actually provide.