-- Migration 004: Analytics layer — SPC flags, yield drivers, anomaly columns
-- Idempotent — safe to run multiple times on PG 15

-- Anomaly detection columns on the raw event table
ALTER TABLE secom_raw
    ADD COLUMN IF NOT EXISTS anomaly_score NUMERIC(10, 6),
    ADD COLUMN IF NOT EXISTS is_anomaly    BOOLEAN;

-- Selected-feature store on the features table (JSONB mirrors secom_raw pattern)
ALTER TABLE secom_features
    ADD COLUMN IF NOT EXISTS features JSONB;

-- SPC violation flags (one row per Western-Electric rule firing)
CREATE TABLE IF NOT EXISTS spc_flags (
    id          SERIAL PRIMARY KEY,
    sensor_name TEXT     NOT NULL,
    raw_id      INTEGER  REFERENCES secom_raw(id),
    ts          TIMESTAMP NOT NULL,
    value       NUMERIC,
    rule_number SMALLINT NOT NULL,  -- 1 = beyond 3σ, 2 = run of 8, 3 = trend of 6, 4 = 2/3 beyond 2σ
    rule_desc   TEXT,
    center_line NUMERIC,
    ucl         NUMERIC,
    lcl         NUMERIC,
    sigma       NUMERIC,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Top yield-impacting sensors from Random Forest
CREATE TABLE IF NOT EXISTS yield_drivers (
    id               SERIAL PRIMARY KEY,
    rank             SMALLINT NOT NULL,
    sensor_name      TEXT     NOT NULL,
    importance_score NUMERIC(10, 8),
    mi_score         NUMERIC(10, 8),
    created_at       TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_spc_flags_sensor      ON spc_flags(sensor_name);
CREATE INDEX IF NOT EXISTS idx_spc_flags_ts          ON spc_flags(ts);
CREATE INDEX IF NOT EXISTS idx_spc_flags_rule        ON spc_flags(rule_number);
CREATE INDEX IF NOT EXISTS idx_spc_flags_raw_id      ON spc_flags(raw_id);
CREATE INDEX IF NOT EXISTS idx_yield_drivers_rank    ON yield_drivers(rank);
CREATE INDEX IF NOT EXISTS idx_secom_raw_anomaly     ON secom_raw(is_anomaly) WHERE is_anomaly = TRUE;
