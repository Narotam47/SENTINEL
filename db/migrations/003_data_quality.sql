-- Migration 003: Data quality tables
-- Idempotent — safe to run multiple times on PG 15

-- One row per execution of validate.py
CREATE TABLE IF NOT EXISTS validation_runs (
    id                    SERIAL PRIMARY KEY,
    run_id                TEXT NOT NULL UNIQUE,
    validated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    batch_id              TEXT,
    n_rows                INTEGER,
    n_sensors             INTEGER,
    overall_quality_score NUMERIC(5,2)
);

-- Per-batch quality summary (one row per batch per validation run)
CREATE TABLE IF NOT EXISTS data_quality (
    id                    SERIAL PRIMARY KEY,
    validation_run_id     INTEGER REFERENCES validation_runs(id) ON DELETE CASCADE,
    batch_id              TEXT    NOT NULL,
    total_rows            INTEGER NOT NULL,
    missing_cell_pct      NUMERIC(6,3),   -- % of all sensor cells that are NULL
    oor_row_pct           NUMERIC(6,3),   -- % of rows with at least one out-of-range reading
    dup_timestamp_count   INTEGER  DEFAULT 0,
    constant_sensor_count INTEGER  DEFAULT 0,
    quality_score         NUMERIC(5,2),
    validated_at          TIMESTAMP DEFAULT NOW()
);

-- Per-sensor quality (one row per sensor per validation run)
CREATE TABLE IF NOT EXISTS sensor_quality (
    id                SERIAL PRIMARY KEY,
    validation_run_id INTEGER REFERENCES validation_runs(id) ON DELETE CASCADE,
    sensor_name       TEXT    NOT NULL,
    missing_pct       NUMERIC(6,3),   -- % of rows where this sensor is NULL
    oor_pct           NUMERIC(6,3),   -- % of non-NULL readings beyond mean ± 3σ
    is_constant       BOOLEAN DEFAULT FALSE,
    quality_score     NUMERIC(5,2),
    validated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_validated  ON validation_runs(validated_at);
CREATE INDEX IF NOT EXISTS idx_data_quality_run_id        ON data_quality(validation_run_id);
CREATE INDEX IF NOT EXISTS idx_data_quality_batch_id      ON data_quality(batch_id);
CREATE INDEX IF NOT EXISTS idx_sensor_quality_run_id      ON sensor_quality(validation_run_id);
CREATE INDEX IF NOT EXISTS idx_sensor_quality_score       ON sensor_quality(quality_score);
CREATE INDEX IF NOT EXISTS idx_sensor_quality_name        ON sensor_quality(sensor_name);
