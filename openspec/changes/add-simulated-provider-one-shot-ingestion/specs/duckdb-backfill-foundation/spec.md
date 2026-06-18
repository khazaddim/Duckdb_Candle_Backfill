## MODIFIED Requirements

### Requirement: V1 Scope Boundary Definition
The backfill module SHALL define and preserve a v1 scope boundary that includes single-provider, single-symbol, single-timeframe jobs running in one owning Python process with DuckDB-backed durable state, plus a deterministic simulated provider harness and one-shot ingestion path for end-to-end fetch-to-store validation.

#### Scenario: In-scope behavior includes deterministic ingestion validation
- **WHEN** maintainers review the Change 2 proposal and implementation checklist
- **THEN** the documented in-scope items include one provider adapter at a time, one symbol per ingestion request, one timeframe per ingestion request, a local simulated `aiohttp` candle server, and a one-shot async fetch-normalize-store path into DuckDB

#### Scenario: Out-of-scope behavior remains explicit after Change 2
- **WHEN** maintainers review Change 2 exclusions
- **THEN** full backfill runner orchestration, gap-detection SQL, retry scheduling, worker dispatch, multi-provider orchestration, and GUI integration remain out of scope

#### Scenario: Change 2 extends but does not replace the storage foundation
- **WHEN** reviewers evaluate Change 2 requirements
- **THEN** the change builds on the existing DuckDB storage foundation and adds provider harness plus one-shot ingestion behavior without weakening prior storage or event-loop-safety requirements

## ADDED Requirements

### Requirement: Simulated Candle Provider Harness
The system SHALL provide a deterministic local `aiohttp` candle service for integration testing the historical candle ingestion path.

#### Scenario: Server lifecycle is test-friendly
- **WHEN** integration tests start and stop the simulated provider harness
- **THEN** the server starts cleanly, exposes a base URL for requests, and shuts down without leaving background resources running

#### Scenario: Endpoint returns aligned candle payloads
- **WHEN** a client issues `GET /products/{product_id}/candles` with inclusive aligned `start`, `end`, and `timeframe_seconds` parameters
- **THEN** the server returns JSON containing metadata for the request plus a `candles` array whose timestamps are aligned to the timeframe grid and ordered ascending by timestamp

#### Scenario: Perfect mode returns the full expected grid
- **WHEN** the harness operates in `perfect` mode for an aligned inclusive range
- **THEN** the response contains the full expected candle set for that range subject only to an explicit request limit

#### Scenario: Truncate-tail mode returns a deterministic incomplete grid
- **WHEN** the harness operates in `truncate_tail` mode for an aligned inclusive range
- **THEN** the response omits a deterministic trailing portion of the expected candle grid while preserving valid ordering and alignment for returned rows

### Requirement: Async Provider Adapter Contract
The system SHALL expose an async provider adapter contract that fetches candles for one symbol over an inclusive time range and returns normalized `Candle` models.

#### Scenario: Adapter exposes async candle fetch signature
- **WHEN** implementers integrate a provider with the backfill package
- **THEN** the provider surface offers an async `fetch_candles(symbol, start_ts, end_ts, timeframe_seconds, limit=None) -> list[Candle]` contract

#### Scenario: Simulated-provider adapter normalizes JSON into Candle models
- **WHEN** the simulated-provider adapter receives a valid JSON response from the local harness
- **THEN** it maps each returned row into a `Candle` object carrying the requested symbol, timeframe, canonical open timestamp, OHLC values, and volume

#### Scenario: Adapter preserves incomplete upstream responses
- **WHEN** the simulated provider returns fewer candles than the full expected grid in `truncate_tail` mode
- **THEN** the adapter returns exactly the normalized subset supplied by the server and does not fabricate missing candles

### Requirement: One-Shot Fetch And Store Ingestion
The system SHALL support a one-shot async ingestion path that fetches candles from the simulated provider and stores them in DuckDB using the existing idempotent candle insert primitive.

#### Scenario: Perfect-mode ingestion stores the expected candle count
- **WHEN** a caller fetches an aligned inclusive range through the simulated-provider adapter in `perfect` mode and inserts the returned candles into a temporary DuckDB database
- **THEN** the stored candle count matches the expected count for that range

#### Scenario: Truncated ingestion stores only the returned subset
- **WHEN** a caller fetches an aligned inclusive range through the simulated-provider adapter in `truncate_tail` mode and inserts the returned candles into DuckDB
- **THEN** the database stores fewer candles than the full expected count while preserving correct keys and timestamps for the returned subset

#### Scenario: One-shot ingestion remains compatible with idempotent writes
- **WHEN** the same one-shot provider response is inserted more than once
- **THEN** the existing candle primary-key and idempotent insert behavior prevent duplicate stored rows

### Requirement: End-To-End Ingestion Test Coverage
The system SHALL include integration coverage proving the simulated provider and one-shot ingestion path work against temporary DuckDB storage.

#### Scenario: Perfect-mode path is tested end to end
- **WHEN** the Change 2 test suite runs
- **THEN** at least one integration test starts the simulated server, fetches candles through the adapter, inserts them into DuckDB, and verifies the expected stored count

#### Scenario: Truncated-mode path is tested end to end
- **WHEN** the Change 2 test suite runs
- **THEN** at least one integration test exercises `truncate_tail` mode and verifies the resulting incomplete stored state is deterministic and inspectable for later validation work