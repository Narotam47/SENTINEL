"""
Phase 3D — Yield Correlation Analysis (Random Forest).

Trains a Random Forest classifier (class_weight='balanced' to handle 14:1
pass/fail imbalance) on selected sensor features and extracts feature
importances as yield drivers.

Outputs:
  • data/exports/yield_feature_importance.csv  (rank, sensor, importance, mi_score)
  • data/exports/yield_model_report.txt        (classification report)
  • yield_drivers table                         (top-10 drivers)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "data" / "exports"
EXPORTS.mkdir(parents=True, exist_ok=True)
IMPORTANCE_CSV  = EXPORTS / "yield_feature_importance.csv"
MODEL_REPORT    = EXPORTS / "yield_model_report.txt"
SELECTED_CSV    = EXPORTS / "selected_features.csv"


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
    """Load selected features from secom_features."""
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

    df = pd.DataFrame(records)
    sensor_cols_sorted = sorted(sensor_cols)
    return df, sensor_cols_sorted


def _load_mi_scores() -> dict[str, float]:
    """Read mutual information scores produced by feature_selection.py."""
    if not SELECTED_CSV.exists():
        return {}
    sel = pd.read_csv(SELECTED_CSV)
    return dict(zip(sel["sensor_name"], sel["mi_score"]))


# ── Model (pure — no DB dependency) ──────────────────────────────────────────

def prepare_xy(
    df: pd.DataFrame,
    sensor_cols: list[str],
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Build X (feature matrix) and y (binary label: 0=pass, 1=fail).
    NaN values are filled with column medians.
    """
    X = df[sensor_cols].copy()
    for col in sensor_cols:
        X[col] = X[col].fillna(X[col].median())
    # Map SECOM labels: −1 (pass) → 0, +1 (fail) → 1
    y = (df["_label"] == 1).astype(int)
    return X, y


def train_random_forest(
    X: pd.DataFrame,
    y: pd.Series,
    test_size: float = 0.20,
    n_estimators: int = 200,
    random_state: int = 42,
) -> tuple[RandomForestClassifier, pd.DataFrame, pd.Series, pd.Series]:
    """
    Stratified train/test split then Random Forest with balanced class weights.
    Returns (model, X_test, y_test, y_pred).
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=random_state
    )
    model = RandomForestClassifier(
        n_estimators=n_estimators,
        class_weight="balanced",
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    y_pred = pd.Series(model.predict(X_test), index=y_test.index)
    return model, X_test, y_test, y_pred


def build_importance_df(
    model: RandomForestClassifier,
    sensor_cols: list[str],
    mi_scores: dict[str, float],
) -> pd.DataFrame:
    importances = pd.Series(model.feature_importances_, index=sensor_cols)
    importances = importances.sort_values(ascending=False)
    return pd.DataFrame(
        {
            "rank":             range(1, len(importances) + 1),
            "sensor_name":      importances.index,
            "importance_score": importances.values,
            "mi_score":         [mi_scores.get(s, float("nan")) for s in importances.index],
        }
    )


# ── Output writers ────────────────────────────────────────────────────────────

def save_classification_report(y_test: pd.Series, y_pred: pd.Series, path: Path) -> None:
    report = classification_report(
        y_test, y_pred, target_names=["pass (−1)", "fail (+1)"]
    )
    path.write_text(report)


def write_yield_drivers(conn, importance_df: pd.DataFrame, top_n: int = 10) -> None:
    top = importance_df.head(top_n)
    records = [
        (
            int(row["rank"]),
            str(row["sensor_name"]),
            float(row["importance_score"]),
            None if pd.isna(row["mi_score"]) else float(row["mi_score"]),
        )
        for _, row in top.iterrows()
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE yield_drivers RESTART IDENTITY")
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO yield_drivers (rank, sensor_name, importance_score, mi_score) VALUES %s",
            records,
            page_size=50,
        )
    conn.commit()


# ── Orchestration ─────────────────────────────────────────────────────────────

def run() -> None:
    print("Phase 3D — Yield Correlation Analysis (Random Forest)")
    print("=" * 60)

    conn = _get_conn()
    try:
        df, sensor_cols = load_features(conn)
        print(f"  Loaded {len(df):,} rows × {len(sensor_cols)} selected sensors")

        fail_count = int((df["_label"] == 1).sum())
        pass_count = len(df) - fail_count
        print(f"  Class distribution: {pass_count} pass  /  {fail_count} fail  "
              f"(ratio {pass_count // fail_count}:1)")

        X, y = prepare_xy(df, sensor_cols)
        model, X_test, y_test, y_pred = train_random_forest(X, y)
        print(f"  Model trained: 200 trees, class_weight='balanced'")
        print(f"  Test set: {len(y_test)} rows  "
              f"({int((y_test == 1).sum())} fail cases)")

        save_classification_report(y_test, y_pred, MODEL_REPORT)
        print(f"  Saved classification report → {MODEL_REPORT}")

        mi_scores = _load_mi_scores()
        importance_df = build_importance_df(model, sensor_cols, mi_scores)
        importance_df.to_csv(IMPORTANCE_CSV, index=False)
        print(f"  Saved feature importances → {IMPORTANCE_CSV}")

        write_yield_drivers(conn, importance_df, top_n=10)
        print("  yield_drivers table updated (top-10)")

        print("\n  Top-10 yield drivers:")
        print(
            importance_df.head(10)
            .to_string(columns=["rank", "sensor_name", "importance_score"], index=False)
        )

        print("\n  Classification Report:")
        print(MODEL_REPORT.read_text())

        print("Yield analysis complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
