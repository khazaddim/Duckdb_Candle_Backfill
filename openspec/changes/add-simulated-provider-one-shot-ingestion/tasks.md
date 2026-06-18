## 1. Simulated Provider Harness
- [ ] 1.1 Add `src/duckdb_candle_backfill/test_server.py` with deterministic aligned candle generation for inclusive ranges.
- [ ] 1.2 Add local `aiohttp` server startup and shutdown helpers suitable for tests.
- [ ] 1.3 Implement `GET /products/{product_id}/candles` with `start`, `end`, and `timeframe_seconds` query handling.
- [ ] 1.4 Implement `perfect` response mode returning the full aligned inclusive grid.
- [ ] 1.5 Implement `truncate_tail` response mode returning a deterministic prefix of the aligned inclusive grid.

## 2. Provider Adapter
- [ ] 2.1 Add `src/duckdb_candle_backfill/providers.py` with the async `CandleProvider` protocol.
- [ ] 2.2 Implement one concrete adapter for the simulated provider using async HTTP requests.
- [ ] 2.3 Normalize provider payloads into `Candle` dataclass instances with canonical timestamp and timeframe fields.
- [ ] 2.4 Ensure adapter results are returned in ascending timestamp order.

## 3. One-Shot Ingestion Slice
- [ ] 3.1 Wire the adapter and existing storage primitives together for a one-shot fetch-and-store path used by tests.
- [ ] 3.2 Initialize a temporary DuckDB file in tests before insertion.
- [ ] 3.3 Insert fetched candles through the existing idempotent storage helper.
- [ ] 3.4 Expose any new public exports needed from `src/duckdb_candle_backfill/__init__.py`.

## 4. Verification
- [ ] 4.1 Add an integration test proving perfect-mode requests return the expected candle count for an aligned range.
- [ ] 4.2 Add an integration test proving truncate-tail mode returns a deterministic incomplete response.
- [ ] 4.3 Add an end-to-end test proving perfect-mode fetch-and-store writes the expected number of rows into DuckDB.
- [ ] 4.4 Add an end-to-end test proving truncated-mode fetch-and-store writes fewer rows while preserving correct timestamp alignment for returned rows.
- [ ] 4.5 Validate the change with `openspec validate add-simulated-provider-one-shot-ingestion --strict`.

## 5. Guardrails
- [ ] 5.1 Do not add gap-detection SQL in this change.
- [ ] 5.2 Do not add worker dispatch or retry scheduling in this change.
- [ ] 5.3 Do not add failure-mode modes beyond `perfect` and `truncate_tail` in this change.