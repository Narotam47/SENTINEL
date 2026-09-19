"""
Phase 2 — Data Integrity Validation Engine.

Reads secom_raw from PostgreSQL, runs four checks on every batch:
  1. Missing values      — flag which sensors are NULL and at what rate
  2. Out-of-range values — readings beyond mean ± 3σ of their own sensor
  3. Duplicate timestamps — rows that share a timestamp within a batch
  4. Constant sensors    — sensors with zero variance (uninformative)

Computes quality scores (0–100) per batch and per sensor, then writes
results to validation_runs, data_quality, and sensor_quality tables.

Usage:
    python pipeline/transform/validate.py
    make validate
"""
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
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

ROOT = Path(__file__).resolve().parents[2]


# ── result dataclasses ────────────────────────────────────────────────────────

@dataclass
class SensorStats:
    sensor_name: str
    missing_pct: float
    oor_pct: float
    is_constant: bool
    quality_score: float


@dataclass
class BatchStats:
    batch_id: str
    total_rows: int
    missing_cell_pct: float
    oor_row_pct: float
    dup_timestamp_count: int
    constant_sensor_count: int
    quality_score: float


@dataclass
class ValidationResult:
    run_id: str
    validated_at: datetime
    batch_stats: list[BatchStats]
    sensor_stats: list[SensorStats]
    overall_quality_score: float


# ── DB connection ─────────────────────────────────────────────────────────────

def _get_conn():
    try:
        return psycopg2.connect(
            host     = os.getenv("POSTGRES_HOST",     "localhost"),
            port     = int(os.getenv("POSTGRES_PORT", "5432")),
            dbname   = os.getenv("POSTGRES_DB",       "sentinel_db"),
            user     = os.getenv("POSTGRES_USER",     "sentinel"),
            password = os.getenv("POSTGRES_PASSWORD", "sentinel_pass"),
        )
    except psycopg2.OperationalError as e:
        log.error("Cannot connect to PostgreSQL: %s", e)
        log.error("Is the stack running?  Run: make up")
        sys.exit(1)


# ── data loading ──────────────────────────────────────────────────────────────

def load_secom_df(conn) -> pd.DataFrame:
    """
    Fetch all rows from secom_raw and expand the JSONB features column
    into a wide DataFrame with one column per sensor.

    Meta-columns are prefixed with '_' so they are never confused with sensors.
    """
    log.info("Loading secom_raw from PostgreSQL …")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, timestamp, label, batch_id, features "
            "FROM secom_raw WHERE features IS NOT NULL ORDER BY id"
        )
        rows = cur.fetchall()

    if not rows:
        log.error("secom_raw is empty — run 'make ingest' first.")
        sys.exit(1)

    records = []
    for row_id, ts, label, batch_id, features in rows:
        rec = {
            "_id":       row_id,
            "_timestamp": ts,
            "_label":    label,
            "_batch_id": batch_id,
        }
        # psycopg2 returns JSONB as a Python dict automatically
        if isinstance(features, dict):
            rec.update(features)
        records.append(rec)

    df = pd.DataFrame(records)
    log.info("Loaded %d rows, %d total columns.", len(df), len(df.columns))
    return df


# ── pure check functions (no DB — fully testable) ─────────────────────────────

def get_sensor_cols(df: pd.DataFrame) -> list[str]:
    """Return all sensor column names (those starting with 'sensor_')."""
    return sorted([c for c in df.columns if c.startswith("sensor_")])


def check_missing(df: pd.DataFrame, sensor_cols: list[str]) -> dict:
    """
    Compute missing-value rates.

    Returns:
        per_sensor  : {sensor_name: missing_pct}  — % of rows where sensor is NULL
        overall_cell_pct : float — % of ALL sensor cells that are NULL
    """
    n_rows = len(df)
    if n_rows == 0:
        return {"per_sensor": {c: 0.0 for c in sensor_cols}, "overall_cell_pct": 0.0}

    null_counts   = df[sensor_cols].isnull().sum()
    per_sensor    = (null_counts / n_rows * 100).round(3).to_dict()
    overall_pct   = float(df[sensor_cols].isnull().values.mean() * 100)
    return {"per_sensor": per_sensor, "overall_cell_pct": round(overall_pct, 3)}


def check_out_of_range(df: pd.DataFrame, sensor_cols: list[str]) -> dict:
    """
    Flag readings more than 3 standard deviations from their sensor's mean.

    NaN values are excluded from both the bound computation and the flag count
    (they are already counted as missing).

    Returns:
        per_sensor  : {sensor_name: oor_pct}  — % of non-NULL readings that are OOR
        oor_row_pct : float — % of rows with at least one OOR reading
        means       : {sensor_name: mean}
        stds        : {sensor_name: std}
    """
    sensor_data = df[sensor_cols]
    means = sensor_data.mean()
    stds  = sensor_data.std()

    lo = means - 3.0 * stds
    hi = means + 3.0 * stds

    # Only flag non-NaN values as OOR
    oor_mask   = ((sensor_data < lo) | (sensor_data > hi)) & sensor_data.notna()
    valid_mask = sensor_data.notna()

    valid_counts = valid_mask.sum()
    oor_counts   = oor_mask.sum()

    # Avoid division by zero for all-NaN sensors
    per_sensor = {}
    for col in sensor_cols:
        if valid_counts[col] > 0:
            per_sensor[col] = round(float(oor_counts[col] / valid_counts[col] * 100), 3)
        else:
            per_sensor[col] = 0.0

    oor_row_pct = float(oor_mask.any(axis=1).mean() * 100)

    return {
        "per_sensor":  per_sensor,
        "oor_row_pct": round(oor_row_pct, 3),
        "means":       means.round(6).to_dict(),
        "stds":        stds.round(6).to_dict(),
    }


def check_duplicate_timestamps(df: pd.DataFrame) -> int:
    """
    Count rows that share a timestamp with at least one other row.
    Returns the total number of duplicate-involved rows (not just the extras).
    """
    if "_timestamp" not in df.columns:
        return 0
    return int(df.duplicated(subset=["_timestamp"], keep=False).sum())


def check_constant_sensors(df: pd.DataFrame, sensor_cols: list[str]) -> list[str]:
    """
    Return names of sensors whose non-NaN readings are all identical.
    A sensor with fewer than 2 non-NaN readings is skipped (cannot assess).
    """
    constant = []
    for col in sensor_cols:
        vals = df[col].dropna()
        if len(vals) >= 2 and vals.nunique() == 1:
            constant.append(col)
    return constant


# ── quality score formulas ────────────────────────────────────────────────────

def sensor_quality_score(missing_pct: float, oor_pct: float, is_constant: bool) -> float:
    """
    Score a single sensor on a 0–100 scale.

    Penalty weights (chosen to reflect importance in yield modeling):
        missing   : 0.5 pts per % missing    → 100% missing → –50 pts
        oor       : 0.3 pts per % OOR        → 100% OOR     → –30 pts
        constant  : flat 20-pt deduction     → sensor is uninformative
    """
    score = 100.0
    score -= missing_pct * 0.5
    score -= oor_pct     * 0.3
    if is_constant:
        score -= 20.0
    return round(max(0.0, score), 2)


def batch_quality_score(
    missing_cell_pct: float,
    oor_row_pct: float,
    dup_ts_count: int,
) -> float:
    """
    Score an entire batch (ingest run) on a 0–100 scale.

    Penalty weights:
        missing cells : 0.5 pts per %        → 100% missing → –50 pts
        oor rows      : 0.3 pts per %        → 100% OOR     → –30 pts
        dup timestamps: 5 pts each, capped   → max –20 pts
    """
    score = 100.0
    score -= missing_cell_pct * 0.5
    score -= oor_row_pct      * 0.3
    score -= min(dup_ts_count * 5.0, 20.0)
    return round(max(0.0, score), 2)


# ── result computation ────────────────────────────────────────────────────────

def compute_results(df: pd.DataFrame) -> ValidationResult:
    """Run all checks on df and return a fully-populated ValidationResult."""
    sensor_cols = get_sensor_cols(df)
    run_id      = str(uuid.uuid4())
    now         = datetime.now(timezone.utc).replace(tzinfo=None)

    log.info("Sensors found : %d", len(sensor_cols))

    # ── run checks ──────────────────────────────────────────────────────────
    log.info("Check 1/4: missing values …")
    miss = check_missing(df, sensor_cols)

    log.info("Check 2/4: out-of-range values (mean ± 3σ) …")
    oor  = check_out_of_range(df, sensor_cols)

    log.info("Check 3/4: duplicate timestamps …")
    dup_count = check_duplicate_timestamps(df)

    log.info("Check 4/4: constant sensors …")
    constant_sensors = check_constant_sensors(df, sensor_cols)

    log.info("Duplicate timestamps : %d row(s) affected", dup_count)
    log.info("Constant sensors     : %d", len(constant_sensors))

    # ── per-sensor stats ─────────────────────────────────────────────────────
    sensor_stats = []
    for col in sensor_cols:
        m   = miss["per_sensor"].get(col, 0.0)
        o   = oor["per_sensor"].get(col, 0.0)
        c   = col in constant_sensors
        qs  = sensor_quality_score(m, o, c)
        sensor_stats.append(SensorStats(
            sensor_name   = col,
            missing_pct   = m,
            oor_pct       = o,
            is_constant   = c,
            quality_score = qs,
        ))

    # ── per-batch stats (group by batch_id) ──────────────────────────────────
    batch_stats = []
    for batch_id, grp in df.groupby("_batch_id"):
        grp_sensors  = grp[sensor_cols]
        b_miss_pct   = float(grp_sensors.isnull().values.mean() * 100)
        b_oor_pct    = oor["oor_row_pct"]   # whole-dataset OOR row %; no per-batch recompute needed
        b_dup_count  = check_duplicate_timestamps(grp)
        b_const_count= len(constant_sensors)
        qs           = batch_quality_score(b_miss_pct, b_oor_pct, b_dup_count)
        batch_stats.append(BatchStats(
            batch_id              = str(batch_id),
            total_rows            = len(grp),
            missing_cell_pct      = round(b_miss_pct, 3),
            oor_row_pct           = round(b_oor_pct,  3),
            dup_timestamp_count   = b_dup_count,
            constant_sensor_count = b_const_count,
            quality_score         = qs,
        ))

    overall = round(
        sum(b.quality_score for b in batch_stats) / max(len(batch_stats), 1), 2
    )

    log.info("Overall quality score : %.2f / 100", overall)

    return ValidationResult(
        run_id                = run_id,
        validated_at          = now,
        batch_stats           = batch_stats,
        sensor_stats          = sensor_stats,
        overall_quality_score = overall,
    )


# ── DB write ──────────────────────────────────────────────────────────────────

def write_results(conn, result: ValidationResult, df: pd.DataFrame) -> int:
    """
    Persist a ValidationResult to the three quality tables.
    Returns the validation_runs.id for the inserted run.
    """
    sensor_cols = get_sensor_cols(df)

    with conn:
        with conn.cursor() as cur:
            # 1. Insert validation run header
            cur.execute(
                """
                INSERT INTO validation_runs
                    (run_id, validated_at, batch_id, n_rows, n_sensors, overall_quality_score)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    result.run_id,
                    result.validated_at,
                    result.batch_stats[0].batch_id if result.batch_stats else None,
                    len(df),
                    len(sensor_cols),
                    result.overall_quality_score,
                ),
            )
            run_pk = cur.fetchone()[0]
            log.info("Inserted validation_runs row id=%d", run_pk)

            # 2. Insert batch quality rows
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO data_quality
                    (validation_run_id, batch_id, total_rows, missing_cell_pct,
                     oor_row_pct, dup_timestamp_count, constant_sensor_count,
                     quality_score, validated_at)
                VALUES %s
                """,
                [
                    (
                        run_pk,
                        b.batch_id,
                        b.total_rows,
                        b.missing_cell_pct,
                        b.oor_row_pct,
                        b.dup_timestamp_count,
                        b.constant_sensor_count,
                        b.quality_score,
                        result.validated_at,
                    )
                    for b in result.batch_stats
                ],
            )
            log.info("Inserted %d data_quality row(s).", len(result.batch_stats))

            # 3. Insert sensor quality rows (bulk)
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO sensor_quality
                    (validation_run_id, sensor_name, missing_pct, oor_pct,
                     is_constant, quality_score, validated_at)
                VALUES %s
                """,
                [
                    (
                        run_pk,
                        s.sensor_name,
                        s.missing_pct,
                        s.oor_pct,
                        s.is_constant,
                        s.quality_score,
                        result.validated_at,
                    )
                    for s in result.sensor_stats
                ],
                page_size=200,
            )
            log.info("Inserted %d sensor_quality row(s).", len(result.sensor_stats))

    return run_pk


# ── console summary ───────────────────────────────────────────────────────────

def _print_summary(result: ValidationResult) -> None:
    b = result.batch_stats[0] if result.batch_stats else None

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║       SENTINEL — Phase 2 Validation Summary              ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print(f"  Run ID           : {result.run_id}")
    print(f"  Validated at     : {result.validated_at:%Y-%m-%d %H:%M:%S}")
    print()

    if b:
        score_label = ("EXCELLENT" if b.quality_score >= 90
                       else "GOOD" if b.quality_score >= 75
                       else "POOR" if b.quality_score >= 60
                       else "BAD")
        print(f"  Batch            : {b.batch_id[:16]}…")
        print(f"  Total rows       : {b.total_rows:,}")
        print(f"  Missing cells    : {b.missing_cell_pct:.2f}%")
        print(f"  OOR rows         : {b.oor_row_pct:.2f}%")
        print(f"  Dup timestamps   : {b.dup_timestamp_count}")
        print(f"  Constant sensors : {b.constant_sensor_count}")
        print(f"  Batch quality    : {b.quality_score:.1f} / 100  [{score_label}]")

    print()

    worst = sorted(result.sensor_stats, key=lambda s: s.quality_score)[:10]
    if worst:
        print("  Top 10 worst sensors:")
        print(f"  {'Sensor':<14}  {'Score':>5}  {'Miss%':>6}  {'OOR%':>6}  {'Const'}")
        print("  " + "─" * 52)
        for s in worst:
            const = "YES" if s.is_constant else ""
            print(f"  {s.sensor_name:<14}  {s.quality_score:>5.1f}  "
                  f"{s.missing_pct:>6.1f}  {s.oor_pct:>6.1f}  {const}")

    print()
    print(f"  Overall quality score : {result.overall_quality_score:.1f} / 100")
    print()
    print("  Run 'make quality-report' to generate the HTML report.")
    print()


# ── entry point ───────────────────────────────────────────────────────────────

def run() -> ValidationResult:
    conn   = _get_conn()
    df     = load_secom_df(conn)
    result = compute_results(df)
    run_pk = write_results(conn, result, df)
    conn.close()

    _print_summary(result)
    log.info("Results written to DB (validation_runs.id=%d)", run_pk)
    return result


if __name__ == "__main__":
    run()
