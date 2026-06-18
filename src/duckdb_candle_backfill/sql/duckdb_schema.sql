CREATE SEQUENCE IF NOT EXISTS backfill_job_id_seq;

CREATE SEQUENCE IF NOT EXISTS backfill_task_id_seq;

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
    raw_json TEXT,
    PRIMARY KEY (provider, market_type, symbol, timeframe_seconds, timestamp)
);

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

CREATE INDEX IF NOT EXISTS idx_candles_lookup
    ON candles (provider, market_type, symbol, timeframe_seconds, timestamp);

CREATE INDEX IF NOT EXISTS idx_backfill_tasks_status_priority
    ON backfill_tasks (status, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_backfill_tasks_job_status
    ON backfill_tasks (job_id, status);