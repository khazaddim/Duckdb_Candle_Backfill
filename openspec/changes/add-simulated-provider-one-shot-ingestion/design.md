## Context
This change is the first end-to-end ingestion slice built on top of the DuckDB storage foundation. The project already has durable storage for candles, jobs, and tasks, plus async-facing storage primitives that keep blocking DuckDB work off the host event-loop thread. What is still missing is a deterministic way to fetch candle data asynchronously, map it into the project model, and prove those rows can be inserted correctly into DuckDB through a realistic integration path.

The host environment is still an asyncio application and may include GUI rendering on the same loop. That means this change must preserve async-first behavior for provider fetching while continuing to rely on the off-loop DuckDB storage rules defined in the foundation change.

This document is self-sufficient for Change 2. It captures the provider harness, adapter contract, normalization rules, one-shot ingestion flow, testing strategy, and scope boundaries without assuming the reader has the larger design note open.

## Goals / Non-Goals
- Goals:
  - Provide a deterministic local `aiohttp` candle server for integration testing.
  - Define one async provider adapter contract and one concrete adapter for the simulated server.
  - Prove a one-shot fetch-normalize-insert path into DuckDB for one symbol and one timeframe.
  - Keep the response model aligned with the canonical candle-open timestamp convention.
  - Cover both complete and intentionally partial provider responses in tests.
- Non-Goals:
  - Full backfill runner orchestration.
  - Task dispatch or task lifecycle updates.
  - SQL validation queries for missing timestamps or contiguous gaps.
  - Retry scheduling and retry exhaustion semantics.
  - Advanced failure modes such as duplicates, out-of-order rows, timeouts, or server errors.
  - GUI integration or progress reporting.

## Scope Boundary

### Included in Change 2
- Local `aiohttp` server startup and shutdown helpers suitable for tests.
- Deterministic candle generation for inclusive aligned ranges.
- One HTTP endpoint: `GET /products/{product_id}/candles`.
- Response modes `perfect` and `truncate_tail`.
- One async provider adapter interface.
- One simulated-provider adapter implementation.
- Normalization into the project's `Candle` dataclass.
- End-to-end tests against temporary `.duckdb` files.

### Excluded from Change 2
- Backfill job runner behavior.
- Pending-task selection, claiming, or worker loops.
- Retry tasks or completeness validation queries.
- Multi-provider routing or multi-symbol orchestration.
- Failure-mode modes reserved for later hardening work.

## Canonical Time And Range Rules
- Candle timestamps represent candle open time in Unix epoch seconds.
- Requests use inclusive range semantics.
- Valid timestamps must align to the timeframe grid.
- For a timeframe `g`, aligned timestamps satisfy `timestamp % g == 0`.
- A full response for `[start, end]` contains `((end - start) // g) + 1` candles.

These rules matter for both server-side generation and client-side assertions.

## Simulated Provider Design

### Server role
The simulated provider is an integration-test harness, not just a unit-test fixture. It exists to exercise the real async HTTP path, produce deterministic candle sequences, and support later completeness-validation work.

### Endpoint contract
- Method: `GET`
- Path: `/products/{product_id}/candles`
- Required query parameters:
  - `start`: inclusive start timestamp
  - `end`: inclusive end timestamp
  - `timeframe_seconds`: candle width in seconds
- Optional query parameters:
  - `limit`: upper bound on returned candle count
  - `mode`: optional per-request response mode when enabled by the harness

### Response contract
The handler returns JSON shaped as:

```json
{
  "product_id": "BTC-USD",
  "timeframe_seconds": 60,
  "start": 1711929600,
  "end": 1711930200,
  "mode": "perfect",
  "candles": [
    {
      "timestamp": 1711929600,
      "open": 100.0,
      "high": 101.0,
      "low": 99.5,
      "close": 100.5,
      "volume": 10.0
    }
  ]
}
```

The exact price-generation function may be synthetic, but it must be deterministic for identical input parameters.

### Generation rules
- Generate aligned timestamps from `start` through `end`, inclusive.
- Produce deterministic OHLCV values from timestamp and product identity so repeated requests are stable.
- Return candles in ascending timestamp order.
- Honor `limit` if present by truncating to the earliest portion of the generated sequence unless a later implementation choice is explicitly documented.

### Required response modes
- `perfect`
  - Returns the full aligned inclusive grid for the requested range, subject only to an explicit `limit`.
- `truncate_tail`
  - Returns a deterministic prefix of the aligned inclusive grid and omits one or more trailing candles.
  - The omitted tail must be stable for identical inputs so tests remain reproducible.

### Server lifecycle expectations
- Tests can start and stop the server cleanly.
- The server exposes its base URL to the adapter.
- Server configuration can choose a default mode for a test, with an optional per-request override if implemented.

## Provider Adapter Design

### Interface
The async provider contract is:

```python
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

### Adapter responsibilities
- Build the request URL and query parameters.
- Perform async HTTP I/O.
- Parse JSON payloads.
- Normalize provider rows into `Candle` objects.
- Set `provider`, `market_type`, `symbol`, and `timeframe_seconds` fields consistently.
- Preserve `volume` when present.
- Return candles in timestamp order.

### Adapter non-responsibilities
- Retry scheduling.
- Gap detection.
- Task dispatch.
- Durable job creation.
- GUI coordination.

### Normalization rules
- `timestamp` in returned `Candle` objects is the candle open timestamp.
- `timeframe_seconds` on every returned candle matches the request.
- `symbol` on returned candles matches the requested product identifier or its mapped canonical symbol.
- The adapter does not fabricate missing candles.
- In `truncate_tail` mode, the adapter returns only the rows supplied by the server.

## One-Shot Ingestion Flow
This change introduces a deliberately small ingestion path:

1. Open or create a temporary DuckDB database using the existing storage helper.
2. Initialize schema using the existing async storage primitive.
3. Start the simulated server in a known mode.
4. Use the simulated-provider adapter to fetch one aligned inclusive range.
5. Normalize the response into `Candle` objects.
6. Insert those candles with the existing idempotent storage primitive.
7. Query DuckDB in tests to verify row count and timestamp coverage.

This flow is enough to prove the project has a real fetch-to-store path without requiring full job orchestration.

## Decisions
- Decision: Use an `aiohttp` test server instead of a pure fake adapter.
  - Rationale: this validates real async HTTP behavior and serialization boundaries.
- Decision: Keep the endpoint surface intentionally small.
  - Rationale: only one endpoint is needed to prove ingestion and avoid early API sprawl.
- Decision: Require deterministic `perfect` and `truncate_tail` modes first.
  - Rationale: these provide one complete and one intentionally incomplete ingestion outcome, which is the minimum useful substrate for later validation work.
- Decision: Keep one-shot ingestion separate from the full runner.
  - Rationale: isolates the fetch-normalize-insert path so later retry and dispatch changes remain reviewable.

## Risks / Trade-offs
- Risk: The harness could be too synthetic to catch realistic adapter issues.
  - Mitigation: use real HTTP transport, explicit query parameters, and deterministic JSON payloads.
- Risk: Scope could drift into validation or retry design.
  - Mitigation: keep this change limited to the fetch-normalize-insert slice and reserve missing-data handling for later changes.
- Risk: Ambiguous response shape could make adapter behavior inconsistent.
  - Mitigation: define the JSON contract explicitly in this document.
- Risk: Limit handling could become underspecified.
  - Mitigation: state that explicit limit truncates the earliest portion of the aligned sequence unless a later spec change revises that rule.

## Test Strategy For Change 2
- Start the simulated server in `perfect` mode and verify it returns the expected inclusive candle count for an aligned range.
- Start the simulated server in `truncate_tail` mode and verify the returned count is deterministically smaller than the full expected count.
- Fetch through the concrete provider adapter and verify normalization into `Candle` objects with correct symbol, timeframe, and timestamps.
- Insert fetched candles into a temporary `.duckdb` file and verify stored row count and key fields.
- Verify perfect-mode one-shot ingestion yields the expected stored count.
- Verify truncated-mode one-shot ingestion yields fewer stored rows while still preserving correct timestamp alignment for the returned subset.

## Planned File Surface
- `src/duckdb_candle_backfill/providers.py`
  - provider protocol and simulated-provider adapter
- `src/duckdb_candle_backfill/test_server.py`
  - local `aiohttp` server harness and deterministic candle generation
- `src/duckdb_candle_backfill/__init__.py`
  - exports for the new provider surface as appropriate
- `tests/test_one_shot_ingestion.py`
  - end-to-end provider and ingestion tests against temporary DuckDB

## Migration Plan
1. Add the simulated provider harness.
2. Add the adapter protocol and simulated-provider adapter.
3. Add one-shot ingestion tests that exercise fetch and insert through the real storage layer.
4. Use this verified ingestion path as the baseline for later validation and retry changes.

## Deferred To Later Changes
- Missing-timestamp detection.
- Contiguous gap compression.
- Job summary queries.
- Pending-task selection and worker loops.
- Retry task generation.
- Duplicate, out-of-order, timeout, empty, and HTTP error modes.
- GUI readiness and cancellation ergonomics.

## Open Questions
- Should the simulated adapter expose `market_type` as a constructor argument or hard-code a single test market type for the first slice?
- Should per-request mode override be part of the first implementation, or should the harness use only a server-wide mode until failure-mode coverage expands?

## Source References
- `backfill_module_design_duckdb.md`
- "Provider Adapter Interface"
- "Simulated Provider / Backfill Validation Harness"
- "Testing Strategy"
- "Implementation Milestones" -> Milestone 2 and Milestone 3