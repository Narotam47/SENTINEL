"""
Phase 3C — Anomaly Detection (Isolation Forest).

Trains an unsupervised Isolation Forest on all selected sensor features and
scores every wafer run.  contamination=0.07 is set slightly above the observed
fail rate (104/1567 ≈ 6.6%) so that mechanical failures are likely captured
without over-flagging normal variation.

Outputs:
  • secom_raw.anomaly_score / secom_raw.is_anomaly  (UPDATE in place)
  • data/exports/anomaly_summary.csv  (monthly breakdown)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from sklearn.ensemble import IsolationForest

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "data" / "exports"
EXPORTS.mkdir(parents=True, exist_ok=True)
ANOMALY_CSV = EXPORTS / "anomaly_summary.csv"

CONTAMINATION = 0.07   # slightly above 6.6% fail rate


# ── DB ────────────────────────────────────────────────────────────────────────

def _get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5433)),
        dbname=os.getenv("DB_NAME", "sentinel_db"),
        user=os.getenv("DB_USER", "sentinel"),
        password=os.getenv("DB_PASSWORD", "sentinel_pass"),
    )


# ── Data loading ──────────────────────────────────────────────────────────────

def load_features(conn) -> tuple[pd.DataFrame, list[str]]:
    """Load selected features from secom_features (populated by feature_selection)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_id, timestamp, label, features "
            "FROM secom_features ORDER BY timestamp"
        )
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError("secom_features is empty — run 'make feature-select' first.")

    sensor_cols: set[str] = set()
    records = []
    for raw_id, ts, label, features in rows:
        rec = {"_id": raw_id, "_timestamp": ts, "_label": label}
        if isinstance(features, dict):
            rec.update(features)
            sensor_cols.update(features.keys())
        records.append(rec)

    df = pd.DataFrame(records).sort_values("_timestamp").reset_index(drop=True)
    sensor_cols_sorted = sorted(sensor_cols)
    return df, sensor_cols_sorted


# ── Model training (pure — no DB dependency) ──────────────────────────────────

def train_isolation_forest(
    X: np.ndarray,
    contamination: float = CONTAMINATION,
) -> tuple[IsolationForest, np.ndarray, np.ndarray]:
    """
    Fit Isolation Forest on X and return (model, scores, predictions).

    decision_function returns scores where lower (more negative) = more anomalous.
    predict returns −1 for anomaly, +1 for normal.
    """
    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)
    scores = model.decision_function(X)   # raw anomaly scores
    preds = model.predict(X)              # −1 or +1
    return model, scores, preds


def build_monthly_summary(df: pd.DataFrame, preds: np.ndarray) -> pd.DataFrame:
    """Aggregate anomaly counts by calendar month."""
    tmp = df[["_timestamp"]].copy()
    tmp["is_anomaly"] = preds == -1
    tmp["month"] = pd.to_datetime(tmp["_timestamp"]).dt.to_period("M").astype(str)

    summary = (
        tmp.groupby("month")
        .agg(total_rows=("is_anomaly", "count"), anomaly_count=("is_anomaly", "sum"))
        .reset_index()
    )
    summary["anomaly_rate_pct"] = (
        summary["anomaly_count"] / summary["total_rows"] * 100
    ).round(2)
    return summary


# ── DB write ──────────────────────────────────────────────────────────────────

def update_anomaly_scores(
    conn,
    raw_ids: list[int],
    scores: np.ndarray,
    preds: np.ndarray,
) -> None:
    """UPDATE secom_raw rows with anomaly_score and is_anomaly."""
    records = [
        (float(scores[i]), bool(preds[i] == -1), int(raw_ids[i]))
        for i in range(len(raw_ids))
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE secom_raw SET anomaly_score = %s, is_anomaly = %s WHERE id = %s",
            records,
            page_size=500,
        )
    conn.commit()


# ── Orchestration ─────────────────────────────────────────────────────────────

def run() -> None:
    print("Phase 3C — Anomaly Detection (Isolation Forest)")
    print("=" * 60)
    print(f"  contamination = {CONTAMINATION}")

    conn = _get_conn()
    try:
        df, sensor_cols = load_features(conn)
        print(f"  Loaded {len(df):,} rows × {len(sensor_cols)} selected sensors")

        # Fill NaN with column medians before training
        X_df = df[sensor_cols].copy()
        for col in sensor_cols:
            X_df[col] = X_df[col].fillna(X_df[col].median())
        X = X_df.values

        model, scores, preds = train_isolation_forest(X, CONTAMINATION)
        n_anomaly = int((preds == -1).sum())
        print(f"  Anomalies flagged: {n_anomaly} / {len(df)} "
              f"({n_anomaly / len(df) * 100:.1f}%)")

        raw_ids = df["_id"].tolist()
        update_anomaly_scores(conn, raw_ids, scores, preds)
        print("  secom_raw updated with anomaly_score / is_anomaly")

        summary = build_monthly_summary(df, preds)
        summary.to_csv(ANOMALY_CSV, index=False)
        print(f"  Saved → {ANOMALY_CSV}")

        print()
        print(summary.to_string(index=False))
        print("\nAnomaly detection complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
