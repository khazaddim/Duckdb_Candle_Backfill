## 1. Scope Freeze
- [ ] 1.1 Document v1 in-scope capabilities (single provider adapter at a time, single symbol, single timeframe, one-process async workers).
- [ ] 1.2 Document v1 out-of-scope items (GUI integration, multi-symbol orchestration, distributed workers, DB-level multi-worker claiming).
- [ ] 1.3 Align README or module docs with the approved v1 boundary.

## 2. Storage Foundation
- [ ] 2.1 Create DuckDB schema objects for candles, backfill_jobs, and backfill_tasks.
- [ ] 2.2 Add required indexes for candle lookup and task queue inspection.
- [ ] 2.3 Add idempotent candle insert statement using conflict-safe semantics.

## 3. Async Storage Primitives
- [ ] 3.1 Implement connection and schema initialization helpers for a local .duckdb file.
- [ ] 3.2 Implement create_backfill_job() primitive.
- [ ] 3.3 Implement enqueue_backfill_tasks() primitive.
- [ ] 3.4 Implement insert_candles() primitive.
- [ ] 3.5 Ensure all blocking DuckDB calls are offloaded from the asyncio event-loop thread.

## 4. Validation Of Foundation
- [ ] 4.1 Add tests for job creation, task enqueue, and idempotent candle insertion.
- [ ] 4.2 Add an event-loop responsiveness test proving DB operations do not stall heartbeat coroutine.
- [ ] 4.3 Validate change with openspec validate add-duckdb-backfill-scope-storage-foundation --strict.
