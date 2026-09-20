"""
Phase 3B — Statistical Process Control (I-MR charts).

Applies I-MR (Individuals and Moving Range) control charts to the top-10
sensors from feature selection and flags Western Electric rule violations.

Western Electric Rules (applied to the Individuals chart):
  Rule 1: Any point beyond UCL or LCL (beyond 3σ from centre)
  Rule 2: 8+ consecutive points on the same side of the centre line
  Rule 3: 6+ consecutive points trending in one direction
  Rule 4: 2 of any 3 consecutive points beyond the 2σ line on the same side

Outputs:
  • spc_flags table (one row per rule violation)

Why I-MR and not X-bar R?
  X-bar charts require subgroups (e.g. 5 wafers per run). SECOM records one
  row per wafer, so there are no natural subgroups — I-MR is the correct chart
  for individual observations.  The moving-range estimate of σ (MR̄/d₂, d₂=1.128
  for n=2) replaces the within-subgroup standard deviation.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]
EXPORTS = ROOT / "data" / "exports"
SELECTED_CSV = EXPORTS / "selected_features.csv"

_D2 = 1.128   # Shewhart constant for moving range of span 2
_D4 = 3.267   # UCL multiplier for MR chart, span 2

RULE_DESCS = {
    1: "Point beyond 3σ control limit",
    2: "8+ consecutive points on same side of centre line",
    3: "6+ consecutive points trending in one direction",
    4: "2 of 3 consecutive points beyond 2σ on same side",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5433)),
        dbname=os.getenv("DB_NAME", "sentinel_db"),
        user=os.getenv("DB_USER", "sentinel"),
        password=os.getenv("DB_PASSWORD", "sentinel_pass"),
    )


# ── Control chart maths (pure — no DB dependency) ────────────────────────────

def compute_imr_limits(values: np.ndarray) -> dict | None:
    """
    Compute I-MR chart parameters from an array of individual observations.

    Returns None when fewer than 2 non-NaN values are present.

    I chart:
        CL  = x̄
        σ̂  = MR̄ / d₂   (d₂ = 1.128 for span-2 moving ranges)
        UCL = CL + 3σ̂
        LCL = CL − 3σ̂

    MR chart:
        CL_mr  = MR̄
        UCL_mr = D₄ × MR̄   (D₄ = 3.267 for span 2)
        LCL_mr = 0          (by Shewhart convention)
    """
    clean = values[~np.isnan(values)]
    if len(clean) < 2:
        return None

    mr = np.abs(np.diff(clean))
    mean_mr = float(np.mean(mr))
    sigma = mean_mr / _D2
    center = float(np.mean(clean))

    return {
        "center":  center,
        "sigma":   sigma,
        "ucl":     center + 3.0 * sigma,
        "lcl":     center - 3.0 * sigma,
        "mean_mr": mean_mr,
        "ucl_mr":  _D4 * mean_mr,
        "lcl_mr":  0.0,
    }


def apply_rule1(vals: np.ndarray, ucl: float, lcl: float) -> list[int]:
    """Indices where individual value exceeds 3σ control limits."""
    return [int(i) for i, v in enumerate(vals) if not np.isnan(v) and (v > ucl or v < lcl)]


def apply_rule2(vals: np.ndarray, center: float) -> list[int]:
    """
    Index of every point that completes a run of 8+ consecutive observations
    on the same side of the centre line.
    """
    flags: list[int] = []
    run = 1
    for i in range(1, len(vals)):
        if np.isnan(vals[i]) or np.isnan(vals[i - 1]):
            run = 1
            continue
        same = (vals[i] > center) == (vals[i - 1] > center)
        not_on_cl = vals[i] != center and vals[i - 1] != center
        if same and not_on_cl:
            run += 1
        else:
            run = 1
        if run >= 8:
            flags.append(int(i))
    return flags


def apply_rule3(vals: np.ndarray) -> list[int]:
    """
    Index of every point that completes a run of 6+ consecutive observations
    all increasing or all decreasing.
    """
    if len(vals) < 6:
        return []

    flags: list[int] = []
    diffs = np.diff(vals)   # length n-1

    for i in range(5, len(vals)):
        window = diffs[i - 5 : i]   # 5 consecutive diffs spanning points i-5..i
        if np.any(np.isnan(window)):
            continue
        if all(d > 0 for d in window) or all(d < 0 for d in window):
            flags.append(int(i))
    return flags


def apply_rule4(vals: np.ndarray, center: float, sigma: float) -> list[int]:
    """
    Index of every point in a 3-point window where at least 2 of the 3 fall
    beyond the 2σ line on the same side of the centre.
    """
    upper_2s = center + 2.0 * sigma
    lower_2s = center - 2.0 * sigma
    flags: list[int] = []

    for i in range(2, len(vals)):
        window = vals[i - 2 : i + 1]
        if np.any(np.isnan(window)):
            continue
        if (sum(v > upper_2s for v in window) >= 2
                or sum(v < lower_2s for v in window) >= 2):
            flags.append(int(i))
    return flags


def apply_all_rules(
    vals: np.ndarray,
    center: float,
    ucl: float,
    lcl: float,
    sigma: float,
) -> list[tuple[int, int]]:
    """Return list of (index, rule_number) for every violation."""
    violations: list[tuple[int, int]] = []
    for idx in apply_rule1(vals, ucl, lcl):
        violations.append((idx, 1))
    for idx in apply_rule2(vals, center):
        violations.append((idx, 2))
    for idx in apply_rule3(vals):
        violations.append((idx, 3))
    for idx in apply_rule4(vals, center, sigma):
        violations.append((idx, 4))
    return violations


# ── Data loading ──────────────────────────────────────────────────────────────

def load_top_sensors(conn, top_n: int = 10) -> tuple[pd.DataFrame, list[str]]:
    """
    Load the top-N sensors from selected_features.csv, then pull their values
    from secom_features (populated by feature_selection.py).
    """
    if not SELECTED_CSV.exists():
        raise FileNotFoundError(
            f"{SELECTED_CSV} not found — run 'make feature-select' first."
        )

    sel = pd.read_csv(SELECTED_CSV)
    top_sensors = sel.nsmallest(top_n, "rank")["sensor_name"].tolist()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_id, timestamp, label, features "
            "FROM secom_features ORDER BY timestamp"
        )
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError("secom_features is empty — run 'make feature-select' first.")

    records = []
    for raw_id, ts, label, features in rows:
        rec = {"_id": raw_id, "_timestamp": ts, "_label": label}
        if isinstance(features, dict):
            for s in top_sensors:
                rec[s] = features.get(s)
        records.append(rec)

    df = pd.DataFrame(records).sort_values("_timestamp").reset_index(drop=True)
    return df, top_sensors


# ── DB write ──────────────────────────────────────────────────────────────────

def write_spc_flags(conn, flag_records: list[dict]) -> None:
    if not flag_records:
        return
    with conn.cursor() as cur:
        cur.execute("TRUNCATE spc_flags RESTART IDENTITY")
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO spc_flags
                (sensor_name, raw_id, ts, value, rule_number, rule_desc,
                 center_line, ucl, lcl, sigma)
            VALUES %s
            """,
            [
                (
                    r["sensor_name"],
                    r["raw_id"],
                    r["ts"],
                    r["value"],
                    r["rule_number"],
                    r["rule_desc"],
                    r["center_line"],
                    r["ucl"],
                    r["lcl"],
                    r["sigma"],
                )
                for r in flag_records
            ],
            page_size=500,
        )
    conn.commit()


# ── Orchestration ─────────────────────────────────────────────────────────────

def analyze_sensor(
    df: pd.DataFrame,
    sensor_name: str,
) -> tuple[dict | None, list[dict]]:
    """
    Run I-MR analysis on one sensor column.
    Returns (limits_dict, list_of_flag_records).
    """
    raw_vals = df[sensor_name].values.astype(float)
    raw_ids = df["_id"].values
    timestamps = df["_timestamp"].values

    # Fill NaN with median for limit/rule computation; NaN rows still generate flags
    median = float(np.nanmedian(raw_vals)) if not np.all(np.isnan(raw_vals)) else 0.0
    filled = np.where(np.isnan(raw_vals), median, raw_vals)

    limits = compute_imr_limits(filled)
    if limits is None:
        return None, []

    violations = apply_all_rules(
        filled,
        limits["center"],
        limits["ucl"],
        limits["lcl"],
        limits["sigma"],
    )

    flag_records = []
    for idx, rule_num in violations:
        ts = timestamps[idx]
        if hasattr(ts, "item"):
            ts = ts.item()
        flag_records.append({
            "sensor_name": sensor_name,
            "raw_id":      int(raw_ids[idx]),
            "ts":          ts,
            "value":       None if np.isnan(raw_vals[idx]) else float(raw_vals[idx]),
            "rule_number": rule_num,
            "rule_desc":   RULE_DESCS[rule_num],
            "center_line": limits["center"],
            "ucl":         limits["ucl"],
            "lcl":         limits["lcl"],
            "sigma":       limits["sigma"],
        })
    return limits, flag_records


def run() -> None:
    print("Phase 3B — Statistical Process Control (I-MR)")
    print("=" * 60)

    conn = _get_conn()
    try:
        df, top_sensors = load_top_sensors(conn, top_n=10)
        print(f"  Loaded {len(df):,} rows, analysing {len(top_sensors)} sensors")

        all_flags: list[dict] = []
        for sensor in top_sensors:
            limits, flags = analyze_sensor(df, sensor)
            if limits is None:
                print(f"  {sensor:20s}  skipped (insufficient data)")
                continue
            print(
                f"  {sensor:20s}  CL={limits['center']:8.3f}  "
                f"UCL={limits['ucl']:8.3f}  LCL={limits['lcl']:8.3f}  "
                f"flags={len(flags)}"
            )
            all_flags.extend(flags)

        write_spc_flags(conn, all_flags)
        print(f"\n  Total flags written to spc_flags: {len(all_flags)}")

        if all_flags:
            rule_counts = {}
            for f in all_flags:
                rule_counts[f["rule_number"]] = rule_counts.get(f["rule_number"], 0) + 1
            for rule_num, count in sorted(rule_counts.items()):
                print(f"    Rule {rule_num}: {count:4d}  ({RULE_DESCS[rule_num]})")

        print("\nSPC analysis complete.")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
