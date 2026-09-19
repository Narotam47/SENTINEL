"""
Phase 1 — loads raw SECOM files into PostgreSQL secom_raw table.

Source files expected at:
  data/raw/secom.data          1567 rows × 590 sensor readings (whitespace-separated)
  data/raw/secom_labels.data   1567 rows: label(-1/1)  date  time

Every ingest run is tagged with a UUID batch_id so rows are fully auditable.
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

ROOT     = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"


# ── DB connection ─────────────────────────────────────────────────────────────

def _conn_params() -> dict:
    return {
        "host":     os.getenv("POSTGRES_HOST",     "localhost"),
        "port":     int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname":   os.getenv("POSTGRES_DB",       "sentinel_db"),
        "user":     os.getenv("POSTGRES_USER",     "sentinel"),
        "password": os.getenv("POSTGRES_PASSWORD", "sentinel_pass"),
    }


def _get_conn():
    params = _conn_params()
    try:
        return psycopg2.connect(**params)
    except psycopg2.OperationalError as e:
        log.error("Cannot connect to PostgreSQL: %s", e)
        log.error("Is the stack running?  Run: make up")
        sys.exit(1)


# ── loading ───────────────────────────────────────────────────────────────────

def load_raw_files() -> pd.DataFrame:
    features_path = DATA_RAW / "secom.data"
    labels_path   = DATA_RAW / "secom_labels.data"

    for p in (features_path, labels_path):
        if not p.exists():
            log.error("Missing source file: %s", p)
            log.error("Download from https://archive.ics.uci.edu/dataset/179/secom")
            log.error("Place secom.data and secom_labels.data in data/raw/")
            sys.exit(1)

    # ── sensor readings ──────────────────────────────────────────────────────
    log.info("Reading sensor data  (%s)", features_path.name)
    features = pd.read_csv(features_path, sep=r"\s+", header=None, engine="python",
                           skipinitialspace=True)
    # Some UCI mirrors prepend a space, creating a spurious all-NaN first column — drop it
    if features.iloc[:, 0].isna().all():
        features = features.iloc[:, 1:].reset_index(drop=True)
    features.columns = [f"sensor_{i}" for i in range(features.shape[1])]
    log.info("  Shape: %d rows × %d sensor columns", *features.shape)

    missing_cells = features.isnull().sum().sum()
    total_cells   = features.size
    log.info("  Missing: %d / %d cells  (%.1f%%)",
             missing_cells, total_cells, missing_cells / total_cells * 100)

    # ── labels ───────────────────────────────────────────────────────────────
    # File format: three whitespace-separated tokens per line: label  date  time
    # e.g.  -1 2008-01-10 15:09:23
    log.info("Reading labels       (%s)", labels_path.name)
    labels_raw = pd.read_csv(
        labels_path,
        sep=r"\s+",
        header=None,
        names=["label", "date_str", "time_str"],
        engine="python",
    )
    labels_raw["timestamp"] = pd.to_datetime(
        labels_raw["date_str"] + " " + labels_raw["time_str"],
        format="%Y-%m-%d %H:%M:%S",
    )
    labels = labels_raw[["label", "timestamp"]].copy()

    pass_n = (labels["label"] == -1).sum()
    fail_n = (labels["label"] ==  1).sum()
    log.info("  Labels — pass: %d  fail: %d  (%.1f%% yield)",
             pass_n, fail_n, pass_n / len(labels) * 100)

    # ── sanity check ─────────────────────────────────────────────────────────
    if len(features) != len(labels):
        log.error("Row count mismatch: %d sensor rows vs %d label rows",
                  len(features), len(labels))
        sys.exit(1)

    df = pd.concat([labels, features], axis=1)
    log.info("Combined dataframe: %d rows × %d columns", *df.shape)
    return df


# ── serialisation helper ──────────────────────────────────────────────────────

def _row_to_json(row: pd.Series, sensor_cols: list[str]) -> str:
    """Serialise a sensor row to a JSON string, converting NaN → null."""
    d = {}
    for col in sensor_cols:
        val = row[col]
        d[col] = None if (isinstance(val, float) and np.isnan(val)) else float(val)
    return json.dumps(d)


# ── ingest ────────────────────────────────────────────────────────────────────

def ingest(df: pd.DataFrame) -> str:
    batch_id        = str(uuid.uuid4())
    ingest_ts       = datetime.now(timezone.utc).replace(tzinfo=None)
    source_file_str = "secom.data + secom_labels.data"
    sensor_cols     = [c for c in df.columns if c.startswith("sensor_")]

    log.info("Batch ID : %s", batch_id)
    log.info("Building insert records …")

    records = []
    for _, row in df.iterrows():
        records.append((
            row["timestamp"],
            int(row["label"]),
            _row_to_json(row, sensor_cols),
            batch_id,
            source_file_str,
            ingest_ts,
        ))

    log.info("Connecting to PostgreSQL …")
    conn = _get_conn()

    try:
        with conn:
            with conn.cursor() as cur:
                # Wipe previous data so re-runs are idempotent
                cur.execute("TRUNCATE secom_raw RESTART IDENTITY CASCADE")
                log.info("Truncated secom_raw (cascade).")

                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO secom_raw
                        (timestamp, label, features, batch_id, source_file, ingest_timestamp)
                    VALUES %s
                    """,
                    records,
                    template="(%s, %s, %s::jsonb, %s, %s, %s)",
                    page_size=200,
                )
                log.info("Inserted %d rows.", len(records))

                # Quick verification
                cur.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM secom_raw")
                count, ts_min, ts_max = cur.fetchone()
                log.info("DB check — rows: %d  ts_range: %s → %s", count, ts_min, ts_max)

                cur.execute(
                    "SELECT label, COUNT(*) FROM secom_raw GROUP BY label ORDER BY label"
                )
                for lbl, cnt in cur.fetchall():
                    name = "pass" if lbl == -1 else "fail"
                    log.info("  label %+d (%s): %d rows", lbl, name, cnt)

    finally:
        conn.close()

    log.info("Ingest complete.  batch_id=%s", batch_id)
    return batch_id


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    df = load_raw_files()
    batch_id = ingest(df)
    print(f"\nIngest succeeded.  batch_id={batch_id}")


if __name__ == "__main__":
    main()
