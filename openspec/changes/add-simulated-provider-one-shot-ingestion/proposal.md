# Change: Add Simulated Provider And One-Shot Ingestion

## Why
The DuckDB backfill foundation now defines durable storage, idempotent candle persistence, and event-loop-safe database access, but it does not yet prove that candles can be fetched asynchronously from a provider, normalized into the project data model, and written into DuckDB through a realistic end-to-end path.

This change creates that first ingestion slice. It adds a deterministic local `aiohttp` candle server, one provider adapter that speaks to that server, and a one-shot fetch-and-store workflow that exercises the real async HTTP path and the existing DuckDB storage primitives together.

This proposal is intentionally self-sufficient for Change 2 review. It includes the needed scope boundaries, provider contract, simulated server behavior, ingestion expectations, testing scenarios, and acceptance criteria so the change can be reviewed without reopening the larger design document.

## What Changes
- Add a simulated candle provider harness implemented as a local `aiohttp` server for deterministic integration testing.
- Add aligned candle generation for inclusive timestamp ranges using the canonical candle-open timestamp convention.
- Add a `GET /products/{product_id}/candles` endpoint with explicit request and response behavior.
- Add deterministic response modes for `perfect` and `truncate_tail` behavior.
- Add a provider adapter interface and one concrete adapter for the simulated server.
- Add a one-shot async ingestion path that fetches a requested aligned range, normalizes provider rows into `Candle` models, and stores them with the existing DuckDB insert primitive.
- Add integration tests that run against temporary `.duckdb` files and verify both perfect and intentionally partial ingestion outcomes.

## Change 2 Scope Summary

### In Scope
- One simulated provider harness running locally in process for tests.
- One provider adapter at a time.
- One-shot ingestion for one requested symbol and one timeframe at a time.
- Async HTTP fetch behavior using the existing event-loop-safe DuckDB storage layer.
- Deterministic candle generation for inclusive aligned ranges.
- Deterministic `perfect` and `truncate_tail` response modes.
- Response normalization into the project's canonical `Candle` model before persistence.
- Integration tests that prove rows land in DuckDB with correct keys and counts.

### Out Of Scope
- Full backfill job orchestration.
- Worker dispatch, task claiming, or task state transitions beyond what Change 1 already established.
- Gap detection SQL, contiguous range compression, retry scheduling, or retry exhaustion behavior.
- Multi-provider orchestration.
- Multi-symbol job planning.
- Failure-mode modes such as duplicate rows, out-of-order rows, empty responses, timeouts, or HTTP 500 responses.
- GUI integration, progress displays, and host-facing controls.

## Simulated Provider Summary

### Endpoint
- Method: `GET`
- Path: `/products/{product_id}/candles`
- Required query parameters:
  - `start`: inclusive start timestamp in Unix epoch seconds
  - `end`: inclusive end timestamp in Unix epoch seconds
  - `timeframe_seconds`: candle width in seconds
- Optional query parameters:
  - `limit`: maximum number of candles to return when explicitly requested by the adapter
  - `mode`: response mode override when the test harness allows per-request mode selection

### Response contract
The simulated server returns JSON with these top-level fields:
- `product_id`
- `timeframe_seconds`
- `start`
- `end`
- `mode`
- `candles`

Each item in `candles` contains:
- `timestamp`
- `open`
- `high`
- `low`
- `close`
- `volume`

### Required modes
- `perfect`: return the full inclusive aligned candle grid for the requested range.
- `truncate_tail`: return a deterministic prefix of the aligned candle grid and omit the trailing candles from the response.

## One-Shot Ingestion Summary
The one-shot ingestion slice added by this change is intentionally narrow:
1. Caller requests one aligned time range for one symbol and timeframe.
2. Provider adapter performs one async HTTP fetch against the simulated server.
3. Adapter normalizes the response into `Candle` models.
4. The existing DuckDB storage primitive inserts the rows idempotently.
5. Tests verify the stored row count and timestamps.

This change does not add the full `run_backfill(...)` orchestration loop. It proves the fetch-to-insert path that later validation, dispatch, and retry changes will build upon.

## Review Focus
- Confirm the simulated provider contract is explicit and deterministic enough for repeatable integration testing.
- Confirm the provider adapter contract is narrow and async-first.
- Confirm the one-shot ingestion slice is the right next step after storage foundation and does not prematurely pull in retry or runner behavior.
- Confirm perfect and intentionally partial responses are both covered so later validation work has a realistic substrate.
- Confirm the planned tests are sufficient to prove end-to-end ingestion into DuckDB through real async HTTP calls.

## Acceptance Summary
- A local simulated candle server can be started and stopped cleanly inside tests.
- The server can return deterministic aligned candles for an inclusive requested range.
- The server supports `perfect` and `truncate_tail` response modes.
- A provider adapter can fetch candles asynchronously from the simulated server and normalize them into `Candle` objects.
- A one-shot fetch-and-store path can insert those candles into a temporary DuckDB database.
- Perfect-mode ingestion stores the expected candle count for the requested range.
- Truncated-mode ingestion stores fewer rows in a way that later validation work can detect as incomplete.

## Impact
- Affected specs: duckdb-backfill-foundation
- Affected code (planned): `src/duckdb_candle_backfill/providers.py`, `src/duckdb_candle_backfill/test_server.py`, `src/duckdb_candle_backfill/__init__.py`, `tests/test_one_shot_ingestion.py`
- Breaking changes: none

## Source Coverage Included Here
This proposal directly incorporates the relevant design details for:
- the async provider adapter contract
- the simulated local `aiohttp` test server
- deterministic aligned candle generation
- the `GET /products/{product_id}/candles` endpoint
- `perfect` and `truncate_tail` response modes
- one-shot fetch, normalization, and DuckDB insert behavior
- temporary DuckDB integration testing

## Source References
- `backfill_module_design_duckdb.md`
- "Provider Adapter Interface"
- "Simulated Provider / Backfill Validation Harness"
- "Chunk Planning" (for inclusive aligned range expectations)
- "Testing Strategy"
- "Implementation Milestones" -> Milestone 2 and Milestone 3
- "Suggested OpenSpec Change Groupings" -> Change 2