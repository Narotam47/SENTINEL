-- SENTINEL: Initial schema
-- Run automatically by PostgreSQL on first container start

-- Raw sensor readings from SECOM dataset
CREATE TABLE IF NOT EXISTS secom_raw (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMP NOT NULL,
    label           SMALLINT NOT NULL,          -- -1 = pass, 1 = fail
    features        JSONB,                       -- sensor columns stored as JSON during EDA
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Cleaned, imputed, feature-engineered table (populated by transform pipeline)
CREATE TABLE IF NOT EXISTS secom_features (
    id              SERIAL PRIMARY KEY,
    raw_id          INTEGER REFERENCES secom_raw(id),
    timestamp       TIMESTAMP NOT NULL,
    label           SMALLINT NOT NULL,
    pass_fail       BOOLEAN GENERATED ALWAYS AS (label = -1) STORED,
    -- top engineered feature columns added by migration 002 after EDA
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Model run metadata
CREATE TABLE IF NOT EXISTS model_runs (
    id              SERIAL PRIMARY KEY,
    run_name        TEXT NOT NULL,
    algorithm       TEXT NOT NULL,
    train_start     TIMESTAMP,
    train_end       TIMESTAMP,
    n_train         INTEGER,
    n_test          INTEGER,
    roc_auc         NUMERIC(6,4),
    f1_score        NUMERIC(6,4),
    precision_score NUMERIC(6,4),
    recall_score    NUMERIC(6,4),
    params          JSONB,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Per-prediction scores (for drift monitoring in Grafana)
CREATE TABLE IF NOT EXISTS predictions (
    id              SERIAL PRIMARY KEY,
    model_run_id    INTEGER REFERENCES model_runs(id),
    feature_id      INTEGER REFERENCES secom_features(id),
    timestamp       TIMESTAMP NOT NULL,
    predicted_label SMALLINT NOT NULL,
    failure_prob    NUMERIC(8,6) NOT NULL,
    actual_label    SMALLINT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Aggregate yield metrics by time window (pre-computed for Grafana)
CREATE TABLE IF NOT EXISTS yield_metrics (
    id              SERIAL PRIMARY KEY,
    window_start    TIMESTAMP NOT NULL,
    window_end      TIMESTAMP NOT NULL,
    window_type     TEXT NOT NULL,              -- 'hourly', 'daily', 'weekly'
    total_units     INTEGER NOT NULL,
    pass_units      INTEGER NOT NULL,
    fail_units      INTEGER NOT NULL,
    yield_rate      NUMERIC(6,4) NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Indexes for Grafana query performance
CREATE INDEX IF NOT EXISTS idx_secom_raw_timestamp      ON secom_raw(timestamp);
CREATE INDEX IF NOT EXISTS idx_secom_features_timestamp ON secom_features(timestamp);
CREATE INDEX IF NOT EXISTS idx_predictions_timestamp    ON predictions(timestamp);
CREATE INDEX IF NOT EXISTS idx_yield_metrics_window     ON yield_metrics(window_start, window_type);
