-- Migration 002: Add audit/lineage columns to secom_raw
-- Safe to run multiple times (ADD COLUMN IF NOT EXISTS is idempotent on PG 9.6+)

ALTER TABLE secom_raw
    ADD COLUMN IF NOT EXISTS batch_id         TEXT,
    ADD COLUMN IF NOT EXISTS source_file      TEXT,
    ADD COLUMN IF NOT EXISTS ingest_timestamp TIMESTAMP;

-- Backfill rows already present before this migration
UPDATE secom_raw
SET
    batch_id         = 'legacy-pre-audit',
    source_file      = 'secom.data + secom_labels.data',
    ingest_timestamp = created_at
WHERE batch_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_secom_raw_batch_id ON secom_raw(batch_id);

-- Propagate audit columns to secom_features so lineage traces end-to-end
ALTER TABLE secom_features
    ADD COLUMN IF NOT EXISTS batch_id TEXT;
