"""
Phase 3A — Feature Selection.

Four-step filter → mutual information ranking:
  1. Drop sensors with >40% missing values
  2. Drop constant (zero-variance) sensors
  3. Drop one sensor from each highly-correlated pair (|r| > 0.95)
  4. Rank surviving sensors by mutual information vs. yield label

Outputs:
  • data/exports/selected_features.csv  (rank, sensor_name, mi_score)
  • secom_features table populated with selected feature values (JSONB)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from sklearn.feature_selection import mutual_info_classif

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "data" / "exports"
EXPORTS.mkdir(parents=True, exist_ok=True)
SELECTED_CSV = EXPORTS / "selected_features.csv"


# ── DB connection ──────────────────────────────────────────────────────────────

def _get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "sentinel_db"),
        user=os.getenv("DB_USER", "sentinel"),
        password=os.getenv("DB_PASSWORD", "sentinel_pass"),
    )


# ── Data loading ───────────────────────────────────────────────────────────────

def load_raw_features(conn) -> pd.DataFrame:
    """Load all secom_raw rows, expanding JSONB features into sensor columns."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, timestamp, label, batch_id, features "
            "FROM secom_raw ORDER BY timestamp"
        )
        rows = cur.fetchall()

    records = []
    for row_id, ts, label, batch_id, features in rows:
        rec = {
            "_id": row_id,
            "_timestamp": ts,
            "_label": label,
            "_batch_id": batch_id,
        }
        if isinstance(features, dict):
            rec.update(features)
        records.append(rec)
    return pd.DataFrame(records)


def get_sensor_cols(df: pd.DataFrame) -> list[str]:
    meta = {"_id", "_timestamp", "_label", "_batch_id"}
    return [c for c in df.columns if c not in meta]


# ── Filtering steps (pure — no DB dependency) ─────────────────────────────────

def step1_drop_high_missing(
    df: pd.DataFrame,
    sensor_cols: list[str],
    threshold: float = 0.40,
) -> tuple[list[str], list[str]]:
    """Return (keep, dropped) splitting on fraction-missing > threshold."""
    miss_rates = df[sensor_cols].isnull().mean()
    keep = miss_rates[miss_rates <= threshold].index.tolist()
    dropped = [c for c in sensor_cols if c not in keep]
    return keep, dropped


def step2_drop_constant(
    df: pd.DataFrame,
    sensor_cols: list[str],
) -> tuple[list[str], list[str]]:
    """Return (keep, dropped) where dropped sensors have zero variance."""
    keep, dropped = [], []
    for col in sensor_cols:
        vals = df[col].dropna()
        if len(vals) >= 2 and vals.nunique() > 1:
            keep.append(col)
        else:
            dropped.append(col)
    return keep, dropped


def step3_drop_correlated(
    df: pd.DataFrame,
    sensor_cols: list[str],
    threshold: float = 0.95,
) -> tuple[list[str], list[str]]:
    """
    Greedy removal of highly-correlated sensors.
    For each pair (i < j) where |corr| > threshold, sensor j is dropped.
    NaN values are filled with column medians before correlation computation.
    """
    filled = df[sensor_cols].copy()
    for col in sensor_cols:
        median = filled[col].median()
        filled[col] = filled[col].fillna(0.0 if np.isnan(median) else median)

    corr = filled.corr().abs()
    to_drop: set[str] = set()
    cols = list(sensor_cols)

    for i in range(len(cols)):
        if cols[i] in to_drop:
            continue
        for j in range(i + 1, len(cols)):
            if cols[j] in to_drop:
                continue
            if corr.loc[cols[i], cols[j]] > threshold:
                to_drop.add(cols[j])

    keep = [c for c in cols if c not in to_drop]
    dropped = [c for c in cols if c in to_drop]
    return keep, dropped


def step4_rank_by_mi(
    df: pd.DataFrame,
    sensor_cols: list[str],
    y: pd.Series,
) -> pd.Series:
    """
    Rank sensors by mutual information vs. binary yield label.
    y must be 0 (pass) / 1 (fail).
    Returns a Series sorted descending by MI score.
    """
    filled = df[sensor_cols].copy()
    for col in sensor_cols:
        median = filled[col].median()
        filled[col] = filled[col].fillna(0.0 if np.isnan(median) else median)

    mi = mutual_info_classif(filled.values, y.values, random_state=42)
    return pd.Series(mi, index=sensor_cols).sort_values(ascending=False)


# ── Output writers ─────────────────────────────────────────────────────────────

def save_csv(mi_scores: pd.Series, out_path: Path) -> None:
    pd.DataFrame(
        {
            "rank": range(1, len(mi_scores) + 1),
            "sensor_name": mi_scores.index,
            "mi_score": mi_scores.values,
        }
    ).to_csv(out_path, index=False)


def write_to_secom_features(
    conn,
    df: pd.DataFrame,
    selected_cols: list[str],
) -> int:
    """TRUNCATE secom_features and re-populate it with selected feature values."""
    records = []
    for _, row in df.iterrows():
        feat: dict = {}
        for col in selected_cols:
            val = row[col]
            feat[col] = None if (isinstance(val, float) and np.isnan(val)) else float(val)

        label = int(row["_label"])
        records.append((
            int(row["_id"]),
            row["_timestamp"],
            label,
            "fail" if label == 1 else "pass",
            str(row["_batch_id"]),
            json.dumps(feat),
        ))

    with conn.cursor() as cur:
        cur.execute("TRUNCATE secom_features RESTART IDENTITY")
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO secom_features
                (raw_id, timestamp, label, pass_fail, batch_id, features)
            VALUES %s
            """,
            records,
            template="(%s, %s, %s, %s, %s, %s::jsonb)",
            page_size=200,
        )
    conn.commit()
    return len(records)


# ── Entry point ────────────────────────────────────────────────────────────────

def run() -> None:
    print("Phase 3A — Feature Selection")
    print("=" * 60)

    conn = _get_conn()
    try:
        df = load_raw_features(conn)
        all_cols = get_sensor_cols(df)
        n_start = len(all_cols)
        print(f"  Loaded {len(df):,} rows × {n_start} sensors")

        keep1, drop1 = step1_drop_high_missing(df, all_cols, threshold=0.40)
        print(f"  Step 1 (>40% missing): dropped {len(drop1):3d}, kept {len(keep1):3d}")

        keep2, drop2 = step2_drop_constant(df, keep1)
        print(f"  Step 2 (constant)     : dropped {len(drop2):3d}, kept {len(keep2):3d}")

        keep3, drop3 = step3_drop_correlated(df, keep2, threshold=0.95)
        print(f"  Step 3 (corr >0.95)  : dropped {len(drop3):3d}, kept {len(keep3):3d}")

        y_binary = (df["_label"] == 1).astype(int)
        mi_scores = step4_rank_by_mi(df, keep3, y_binary)
        print(f"  Step 4 (MI ranking)   : top = {mi_scores.index[0]}, "
              f"score = {mi_scores.iloc[0]:.4f}")

        save_csv(mi_scores, SELECTED_CSV)
        print(f"  Saved → {SELECTED_CSV}")

        n_written = write_to_secom_features(conn, df, keep3)
        print(f"  secom_features: {n_written:,} rows written")

        print()
        print(f"  {n_start} → {len(keep3)} sensors selected "
              f"({n_start - len(keep3)} dropped total)")
        print("\nFeature selection complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
