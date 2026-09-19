"""
SECOM Data Profiler — run before ingest to validate source files.

Outputs a structured report to stdout and saves it to
data/exports/secom_profile.txt for later reference.

Usage:
    python pipeline/ingest/profile_secom.py
    make profile
"""
import os
import sys
from pathlib import Path
from io import StringIO

import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

ROOT     = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
EXPORTS  = ROOT / "data" / "exports"


# ── helpers ──────────────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 30) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _load_files() -> tuple[pd.DataFrame, pd.DataFrame]:
    features_path = DATA_RAW / "secom.data"
    labels_path   = DATA_RAW / "secom_labels.data"

    for p in (features_path, labels_path):
        if not p.exists():
            print(f"ERROR: missing file {p}")
            print("Download from https://archive.ics.uci.edu/dataset/179/secom")
            print("Place secom.data and secom_labels.data in data/raw/")
            sys.exit(1)

    features = pd.read_csv(features_path, sep=r"\s+", header=None, engine="python",
                           skipinitialspace=True)
    if features.iloc[:, 0].isna().all():
        features = features.iloc[:, 1:].reset_index(drop=True)
    features.columns = [f"sensor_{i}" for i in range(features.shape[1])]

    # Labels file: 3 whitespace-separated tokens — label, date, time
    labels_raw = pd.read_csv(
        labels_path, sep=r"\s+", header=None,
        names=["label", "date_str", "time_str"], engine="python"
    )
    labels_raw["timestamp"] = pd.to_datetime(
        labels_raw["date_str"] + " " + labels_raw["time_str"],
        format="%Y-%m-%d %H:%M:%S"
    )
    labels = labels_raw[["label", "timestamp"]].copy()

    return features, labels


def _missing_summary(features: pd.DataFrame) -> pd.DataFrame:
    missing = features.isnull().sum()
    pct     = missing / len(features) * 100
    summary = pd.DataFrame({
        "missing_count": missing,
        "missing_pct":   pct.round(2),
    })
    return summary.sort_values("missing_pct", ascending=False)


# ── report ────────────────────────────────────────────────────────────────────

def profile() -> str:
    out = StringIO()

    def p(*args, **kw):
        print(*args, **kw, file=out)

    features, labels = _load_files()
    df_miss = _missing_summary(features)

    # ── header ──
    p()
    p("╔══════════════════════════════════════════════════════════╗")
    p("║          SENTINEL — SECOM Raw Data Profile               ║")
    p("╚══════════════════════════════════════════════════════════╝")
    p()

    # ── shape ──
    n_rows, n_sensor = features.shape
    p("── SHAPE ───────────────────────────────────────────────────")
    p(f"  Rows         : {n_rows:,}")
    p(f"  Sensor cols  : {n_sensor:,}")
    p(f"  Total cols   : {n_sensor + 2:,}  (sensors + label + timestamp)")
    p()

    # ── timestamps ──
    ts_min = labels["timestamp"].min()
    ts_max = labels["timestamp"].max()
    ts_range = ts_max - ts_min
    p("── TIMESTAMPS ──────────────────────────────────────────────")
    p(f"  First record : {ts_min}")
    p(f"  Last record  : {ts_max}")
    p(f"  Span         : {ts_range.days} days  ({ts_range})")
    p(f"  Dtype        : {labels['timestamp'].dtype}")
    p()

    # ── class imbalance ──
    pass_count = (labels["label"] == -1).sum()
    fail_count = (labels["label"] ==  1).sum()
    pass_pct   = pass_count / n_rows * 100
    fail_pct   = fail_count / n_rows * 100
    ratio      = pass_count / max(fail_count, 1)
    p("── YIELD / CLASS BALANCE ───────────────────────────────────")
    p(f"  Pass (-1) : {pass_count:5,}  ({pass_pct:5.1f}%)  {_bar(pass_pct)}")
    p(f"  Fail  (+1) : {fail_count:5,}  ({fail_pct:5.1f}%)  {_bar(fail_pct)}")
    p(f"  Imbalance ratio : {ratio:.1f} : 1  (pass : fail)")
    p(f"  NOTE: class imbalance requires SMOTE or class_weight in modeling")
    p()

    # ── missing values overview ──
    n_zero_miss   = (df_miss["missing_pct"] == 0).sum()
    n_any_miss    = (df_miss["missing_pct"] > 0).sum()
    n_all_miss    = (df_miss["missing_pct"] == 100).sum()
    n_high_miss   = (df_miss["missing_pct"] > 50).sum()
    overall_miss  = features.isnull().values.mean() * 100

    p("── MISSING VALUES ──────────────────────────────────────────")
    p(f"  Overall cell missing rate   : {overall_miss:.2f}%")
    p(f"  Columns with no missing     : {n_zero_miss:,}")
    p(f"  Columns with any missing    : {n_any_miss:,}")
    p(f"  Columns > 50% missing       : {n_high_miss:,}  (drop candidates)")
    p(f"  Columns 100% missing        : {n_all_miss:,}  (dead sensors)")
    p()

    # missing histogram by bucket
    buckets = [(0, 0), (1, 10), (11, 25), (26, 50), (51, 75), (76, 99), (100, 100)]
    p("  Missing % distribution:")
    for lo, hi in buckets:
        if lo == hi:
            count = (df_miss["missing_pct"] == lo).sum()
            label = f"{lo}%"
        else:
            count = ((df_miss["missing_pct"] >= lo) & (df_miss["missing_pct"] <= hi)).sum()
            label = f"{lo}–{hi}%"
        bar = "▪" * min(count, 40)
        p(f"    {label:10s} : {count:3d} cols  {bar}")
    p()

    # top 20 worst columns
    top20 = df_miss[df_miss["missing_pct"] > 0].head(20)
    if not top20.empty:
        p("  Top columns by missing %:")
        for col, row in top20.iterrows():
            p(f"    {col:12s} : {row['missing_pct']:6.1f}%  {_bar(row['missing_pct'], 20)}")
    p()

    # ── variance / constant columns ──
    std_vals     = features.std(numeric_only=True)
    n_zero_var   = (std_vals == 0).sum()
    n_near_zero  = (std_vals < 1e-6).sum()
    p("── VARIANCE ────────────────────────────────────────────────")
    p(f"  Zero-variance columns  : {n_zero_var}")
    p(f"  Near-zero (< 1e-6) std : {n_near_zero}  (likely constant sensors)")
    p()

    # ── dtypes ──
    dtype_counts = features.dtypes.value_counts()
    p("── DATA TYPES ──────────────────────────────────────────────")
    for dtype, count in dtype_counts.items():
        p(f"  {str(dtype):10s} : {count:,} columns")
    p()

    # ── sensor value ranges (sample) ──
    numeric_stats = features.describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).T
    numeric_stats = numeric_stats[["min", "5%", "50%", "95%", "max", "std"]]
    p("── SENSOR VALUE STATS (non-missing cells) ──────────────────")
    p(f"  Min across all sensors  : {numeric_stats['min'].min():.4g}")
    p(f"  Max across all sensors  : {numeric_stats['max'].max():.4g}")
    p(f"  Median of sensor medians: {numeric_stats['50%'].median():.4g}")
    p(f"  Mean of sensor std devs : {numeric_stats['std'].mean():.4g}")
    p()

    p("── INGEST READINESS ────────────────────────────────────────")
    p(f"  ✓ Both source files found")
    p(f"  ✓ {n_rows:,} rows to ingest")
    if n_all_miss > 0:
        p(f"  ⚠  {n_all_miss} fully-empty sensor columns — will store NaN in DB")
    if n_zero_var > 0:
        p(f"  ⚠  {n_zero_var} zero-variance columns — flag for removal in Phase 2")
    p(f"  ✓ Profile complete — proceed with: make ingest")
    p()

    return out.getvalue()


def main():
    EXPORTS.mkdir(parents=True, exist_ok=True)
    report = profile()
    print(report)
    out_path = EXPORTS / "secom_profile.txt"
    out_path.write_text(report)
    print(f"Profile saved → {out_path}")


if __name__ == "__main__":
    main()
