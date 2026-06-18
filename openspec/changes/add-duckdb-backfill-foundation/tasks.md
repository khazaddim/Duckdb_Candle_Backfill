## 1. Scope Freeze
- [ ] 1.1 Document v1 in-scope capabilities: one provider adapter at a time, one symbol per job, one timeframe per job, DuckDB-backed durable state, and one-process async ownership.
- [ ] 1.2 Document v1 out-of-scope items: GUI integration, multi-provider orchestration, multi-symbol scheduling, distributed workers, DB-level multi-worker claiming, and retry-engine behavior.
- [ ] 1.3 Record the Change 1 review focus and acceptance summary in the proposal and design docs.

## 2. Storage Foundation
- [ ] 2.1 Create DuckDB schema objects for `candles`, `backfill_jobs`, and `backfill_tasks` with the required fields described in the Change 1 design.
- [ ] 2.2 Add required indexes for candle lookup, task queue inspection, and job-task inspection.
- [ ] 2.3 Add identifier generation for job and task primary keys using DuckDB-compatible identity semantics.
- [ ] 2.4 Add idempotent candle insert behavior using conflict-safe semantics on the candle primary key.

## 3. Async Storage Primitives
- [ ] 3.1 Implement a connection helper for opening or creating a local `.duckdb` file.
- [ ] 3.2 Implement a schema initialization helper that is safe to run repeatedly.
- [ ] 3.3 Implement `create_backfill_job()` to persist requested and aligned range metadata plus status and retry settings.
- [ ] 3.4 Implement `enqueue_backfill_tasks()` to create one pending task row per planned range.
- [ ] 3.5 Implement `insert_candles()` with idempotent persistence semantics and an inserted-row count or equivalent success result.
- [ ] 3.6 Ensure all blocking DuckDB calls are offloaded from the asyncio event-loop thread via `asyncio.to_thread(...)` or an equivalent off-loop worker strategy.

## 4. Validation Of Foundation
- [ ] 4.1 Add a schema initialization test against a fresh temporary `.duckdb` file.
- [ ] 4.2 Add tests for job creation, task enqueue, and idempotent candle insertion.
- [ ] 4.3 Add an event-loop responsiveness test proving DB operations do not stall a concurrent heartbeat coroutine.
- [ ] 4.4 Validate the change with `openspec validate add-duckdb-backfill-foundation --strict`.

## 5. Out-Of-Scope Guardrails
- [ ] 5.1 Do not add provider HTTP logic in Change 1.
- [ ] 5.2 Do not add validation gap queries or retry orchestration in Change 1.
- [ ] 5.3 Do not add multi-process dispatch or GUI-facing integration work in Change 1.
