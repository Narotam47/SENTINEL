"""
Phase 2 tests — Validation Rules Engine.

All tests are pure unit tests: no DB connection, no data files required.
Each test constructs a small DataFrame and exercises one validation function.
"""
import math

import numpy as np
import pandas as pd
import pytest

from pipeline.transform.validate import (
    batch_quality_score,
    check_constant_sensors,
    check_duplicate_timestamps,
    check_missing,
    check_out_of_range,
    get_sensor_cols,
    sensor_quality_score,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_df(**sensor_values) -> pd.DataFrame:
    """
    Build a minimal DataFrame shaped like the output of load_secom_df().
    Pass keyword args as sensor_name=list_of_values.
    """
    n = max(len(v) for v in sensor_values.values())
    data = {
        "_id":        list(range(n)),
        "_timestamp": pd.date_range("2020-01-01", periods=n, freq="h"),
        "_label":     [-1] * n,
        "_batch_id":  ["test-batch"] * n,
    }
    data.update(sensor_values)
    return pd.DataFrame(data)


# ── get_sensor_cols ───────────────────────────────────────────────────────────

def test_get_sensor_cols_returns_only_sensor_columns():
    df = _make_df(sensor_0=[1.0, 2.0], sensor_1=[3.0, 4.0])
    cols = get_sensor_cols(df)
    assert cols == ["sensor_0", "sensor_1"]
    assert "_id" not in cols
    assert "_timestamp" not in cols


# ── check_missing ──────────────────────────────────────────────────────────────

def test_missing_half_null():
    df = _make_df(
        sensor_0=[1.0, float("nan"), 1.0, float("nan")],  # 50% missing
        sensor_1=[1.0, 1.0, 1.0, 1.0],                    # 0% missing
    )
    result = check_missing(df, ["sensor_0", "sensor_1"])
    assert abs(result["per_sensor"]["sensor_0"] - 50.0) < 0.01
    assert result["per_sensor"]["sensor_1"] == pytest.approx(0.0)
    assert abs(result["overall_cell_pct"] - 25.0) < 0.01  # (2 null / 8 cells)


def test_missing_all_null():
    df = _make_df(sensor_0=[float("nan")] * 4)
    result = check_missing(df, ["sensor_0"])
    assert result["per_sensor"]["sensor_0"] == pytest.approx(100.0)
    assert result["overall_cell_pct"] == pytest.approx(100.0)


def test_missing_none_null():
    df = _make_df(sensor_0=[1.0, 2.0, 3.0])
    result = check_missing(df, ["sensor_0"])
    assert result["per_sensor"]["sensor_0"] == pytest.approx(0.0)
    assert result["overall_cell_pct"] == pytest.approx(0.0)


# ── check_out_of_range ────────────────────────────────────────────────────────

def test_oor_detects_clear_outlier():
    # 100 values tightly clustered around 0, plus one extreme outlier
    normal = [0.0] * 100
    df = _make_df(sensor_0=normal + [1_000_000.0])
    result = check_out_of_range(df, ["sensor_0"])
    # Outlier should be flagged
    assert result["per_sensor"]["sensor_0"] > 0


def test_oor_all_identical_no_flag():
    # Constant sensor: std=0, bounds=[mean,mean], so identical values are NOT OOR
    df = _make_df(sensor_0=[5.0] * 10)
    result = check_out_of_range(df, ["sensor_0"])
    assert result["per_sensor"]["sensor_0"] == pytest.approx(0.0)


def test_oor_ignores_nan_in_count():
    # NaN cells should not be counted as OOR
    vals = [1.0, float("nan"), 1.0, float("nan"), 1.0]
    df = _make_df(sensor_0=vals)
    result = check_out_of_range(df, ["sensor_0"])
    # All non-NaN values are identical → no OOR
    assert result["per_sensor"]["sensor_0"] == pytest.approx(0.0)


def test_oor_row_pct_reflects_rows_with_any_oor():
    # sensor_0 has one outlier in row 0; sensor_1 is clean
    vals_s0 = [0.0] * 50 + [1_000_000.0]  # 1 outlier
    vals_s1 = [1.0] * 51                   # all clean
    df = _make_df(sensor_0=vals_s0, sensor_1=vals_s1)
    result = check_out_of_range(df, ["sensor_0", "sensor_1"])
    # At least 1 row should be flagged
    assert result["oor_row_pct"] > 0


# ── check_duplicate_timestamps ────────────────────────────────────────────────

def test_duplicate_timestamps_detected():
    df = _make_df(sensor_0=[1.0, 2.0, 3.0, 4.0])
    # Override timestamps to create a duplicate
    ts = list(df["_timestamp"])
    ts[1] = ts[0]   # row 0 and 1 share a timestamp
    df["_timestamp"] = ts
    count = check_duplicate_timestamps(df)
    assert count == 2   # both rows involved in the duplicate are counted


def test_no_duplicate_timestamps():
    df = _make_df(sensor_0=[1.0, 2.0, 3.0])
    # Default _make_df gives unique hourly timestamps
    assert check_duplicate_timestamps(df) == 0


def test_all_duplicate_timestamps():
    df = _make_df(sensor_0=[1.0, 2.0, 3.0])
    df["_timestamp"] = pd.Timestamp("2020-01-01 00:00:00")   # all same
    assert check_duplicate_timestamps(df) == 3


# ── check_constant_sensors ────────────────────────────────────────────────────

def test_constant_sensor_detected():
    df = _make_df(
        sensor_0=[7.5] * 10,             # constant
        sensor_1=list(range(10)),         # not constant
    )
    constants = check_constant_sensors(df, ["sensor_0", "sensor_1"])
    assert "sensor_0" in constants
    assert "sensor_1" not in constants


def test_constant_sensor_with_nans():
    # sensor is constant among non-NaN values
    df = _make_df(
        sensor_0=[3.0, float("nan"), 3.0, float("nan"), 3.0],
    )
    constants = check_constant_sensors(df, ["sensor_0"])
    assert "sensor_0" in constants


def test_all_nan_sensor_not_flagged_as_constant():
    # All NaN → less than 2 non-NaN readings → skip
    df = _make_df(sensor_0=[float("nan")] * 5)
    constants = check_constant_sensors(df, ["sensor_0"])
    assert "sensor_0" not in constants


def test_single_value_sensor_not_flagged():
    # Only 1 non-NaN reading → cannot assess constant
    df = _make_df(sensor_0=[float("nan"), 5.0, float("nan")])
    constants = check_constant_sensors(df, ["sensor_0"])
    assert "sensor_0" not in constants


# ── sensor_quality_score ──────────────────────────────────────────────────────

def test_sensor_score_perfect():
    assert sensor_quality_score(0.0, 0.0, False) == pytest.approx(100.0)


def test_sensor_score_all_missing():
    # 100% missing → −50 pts
    assert sensor_quality_score(100.0, 0.0, False) == pytest.approx(50.0)


def test_sensor_score_all_oor():
    # 100% OOR → −30 pts
    assert sensor_quality_score(0.0, 100.0, False) == pytest.approx(70.0)


def test_sensor_score_constant_penalty():
    # Clean but constant → −20 pts
    assert sensor_quality_score(0.0, 0.0, True) == pytest.approx(80.0)


def test_sensor_score_never_negative():
    # Worst possible case: all penalties applied
    assert sensor_quality_score(100.0, 100.0, True) == pytest.approx(0.0)


def test_sensor_score_combined():
    # 40% missing (−20), 10% OOR (−3), constant (−20) → 100−20−3−20 = 57
    assert sensor_quality_score(40.0, 10.0, True) == pytest.approx(57.0)


# ── batch_quality_score ───────────────────────────────────────────────────────

def test_batch_score_perfect():
    assert batch_quality_score(0.0, 0.0, 0) == pytest.approx(100.0)


def test_batch_score_missing_penalty():
    # 20% missing → −10 pts
    assert batch_quality_score(20.0, 0.0, 0) == pytest.approx(90.0)


def test_batch_score_oor_penalty():
    # 10% OOR rows → −3 pts
    assert batch_quality_score(0.0, 10.0, 0) == pytest.approx(97.0)


def test_batch_score_dup_ts_penalty():
    # 2 dup rows → −10 pts
    assert batch_quality_score(0.0, 0.0, 2) == pytest.approx(90.0)


def test_batch_score_dup_ts_capped():
    # Many dups → capped at −20 pts
    assert batch_quality_score(0.0, 0.0, 100) == pytest.approx(80.0)


def test_batch_score_never_negative():
    assert batch_quality_score(100.0, 100.0, 100) == pytest.approx(0.0)
