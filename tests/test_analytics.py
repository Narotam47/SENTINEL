"""
Phase 3 tests — Analytics Layer.

All tests are pure unit tests: no DB connection, no data files, no Docker.
Each test exercises a single function with small synthetic data.
"""

import numpy as np
import pandas as pd
import pytest

from pipeline.transform.feature_selection import (
    get_sensor_cols,
    step1_drop_high_missing,
    step2_drop_constant,
    step3_drop_correlated,
    step4_rank_by_mi,
)
from pipeline.analytics.spc import (
    apply_all_rules,
    apply_rule1,
    apply_rule2,
    apply_rule3,
    apply_rule4,
    compute_imr_limits,
)
from pipeline.analytics.anomaly import build_monthly_summary, train_isolation_forest
from pipeline.analytics.yield_analysis import build_importance_df, prepare_xy


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(**sensor_values) -> pd.DataFrame:
    """Build a minimal DataFrame shaped like the output of load_raw_features()."""
    n = max(len(v) for v in sensor_values.values())
    data = {
        "_id":        list(range(n)),
        "_timestamp": pd.date_range("2020-01-01", periods=n, freq="h"),
        "_label":     [-1] * n,
        "_batch_id":  ["test"] * n,
    }
    data.update(sensor_values)
    return pd.DataFrame(data)


# ── Part A: Feature Selection ─────────────────────────────────────────────────

def test_step1_drops_sensor_above_threshold():
    df = _make_df(
        sensor_0=[float("nan")] * 5 + [1.0] * 5,  # 50% missing → dropped
        sensor_1=[1.0] * 10,                        # 0% missing → kept
    )
    keep, dropped = step1_drop_high_missing(df, ["sensor_0", "sensor_1"], threshold=0.40)
    assert "sensor_0" in dropped
    assert "sensor_1" in keep


def test_step1_keeps_sensor_at_threshold():
    # 40% missing == threshold → kept (condition is strictly > threshold)
    df = _make_df(sensor_0=[float("nan")] * 4 + [1.0] * 6)
    keep, dropped = step1_drop_high_missing(df, ["sensor_0"], threshold=0.40)
    assert "sensor_0" in keep
    assert dropped == []


def test_step2_drops_constant_sensor():
    df = _make_df(
        sensor_0=[7.5] * 10,          # constant → dropped
        sensor_1=list(range(10)),     # varies → kept
    )
    keep, dropped = step2_drop_constant(df, ["sensor_0", "sensor_1"])
    assert "sensor_0" in dropped
    assert "sensor_1" in keep


def test_step2_keeps_sensor_with_nan_and_variation():
    df = _make_df(sensor_0=[1.0, float("nan"), 2.0, float("nan"), 3.0])
    keep, dropped = step2_drop_constant(df, ["sensor_0"])
    assert "sensor_0" in keep
    assert dropped == []


def test_step2_drops_all_nan_sensor():
    # All NaN → fewer than 2 non-NaN readings → treated as cannot-assess → dropped
    df = _make_df(sensor_0=[float("nan")] * 5)
    keep, dropped = step2_drop_constant(df, ["sensor_0"])
    assert "sensor_0" in dropped


def test_step3_drops_one_from_correlated_pair():
    # sensor_0 and sensor_1 are perfectly correlated (linear transform)
    x = np.linspace(0, 1, 20)
    df = _make_df(
        sensor_0=x.tolist(),
        sensor_1=(x * 2 + 1).tolist(),   # corr = 1.0 with sensor_0
        sensor_2=np.random.default_rng(0).random(20).tolist(),  # independent
    )
    keep, dropped = step3_drop_correlated(df, ["sensor_0", "sensor_1", "sensor_2"])
    # The greedy algorithm keeps sensor_0 (earlier index) and drops sensor_1
    assert "sensor_0" in keep
    assert "sensor_1" in dropped
    assert "sensor_2" in keep  # independent sensor is retained


def test_step3_keeps_uncorrelated_sensors():
    rng = np.random.default_rng(42)
    df = _make_df(
        sensor_0=rng.random(50).tolist(),
        sensor_1=rng.random(50).tolist(),
    )
    keep, dropped = step3_drop_correlated(df, ["sensor_0", "sensor_1"], threshold=0.95)
    # Randomly generated vectors have low correlation → both kept
    assert len(keep) == 2
    assert dropped == []


def test_step4_rank_by_mi_returns_series_sorted_descending():
    # sensor_0 perfectly predicts label; sensor_1 is pure noise
    rng = np.random.default_rng(7)
    n = 100
    label = (rng.integers(0, 2, n)).tolist()
    df = _make_df(
        sensor_0=[float(v) for v in label],              # MI with label should be high
        sensor_1=rng.random(n).tolist(),                  # MI with label should be low
        _label=[-1 if v == 0 else 1 for v in label],
    )
    # Override _label so it matches sensor_0
    df["_label"] = [-1 if v == 0 else 1 for v in label]
    y = (df["_label"] == 1).astype(int)
    mi = step4_rank_by_mi(df, ["sensor_0", "sensor_1"], y)
    assert list(mi.index) == sorted(mi.index, key=lambda s: -mi[s])  # descending
    assert mi["sensor_0"] >= mi["sensor_1"]


# ── Part B: SPC — I-MR chart maths ───────────────────────────────────────────

def test_compute_imr_limits_known_constant_mr():
    # All moving ranges = 1 → mean_mr = 1 → sigma = 1/1.128
    vals = np.arange(1.0, 11.0)  # 1,2,...,10
    limits = compute_imr_limits(vals)
    assert limits is not None
    assert limits["center"] == pytest.approx(5.5, rel=1e-6)
    expected_sigma = 1.0 / 1.128
    assert limits["sigma"] == pytest.approx(expected_sigma, rel=1e-4)
    assert limits["ucl"] == pytest.approx(5.5 + 3.0 * expected_sigma, rel=1e-4)
    assert limits["lcl"] == pytest.approx(5.5 - 3.0 * expected_sigma, rel=1e-4)


def test_compute_imr_limits_returns_none_for_single_value():
    assert compute_imr_limits(np.array([5.0])) is None


def test_apply_rule1_flags_beyond_3sigma():
    center, sigma = 0.0, 1.0
    ucl, lcl = center + 3 * sigma, center - 3 * sigma
    vals = np.array([0.0, 0.5, -0.5, 4.0, 0.0, -4.0])
    flags = apply_rule1(vals, ucl, lcl)
    assert 3 in flags   # 4.0 > UCL
    assert 5 in flags   # -4.0 < LCL
    assert 0 not in flags
    assert 1 not in flags


def test_apply_rule2_flags_eighth_in_run():
    center = 0.0
    # 8 consecutive points above centre
    vals = np.array([1.0] * 8 + [0.0])
    flags = apply_rule2(vals, center)
    assert 7 in flags  # 8th point (index 7) completes the run


def test_apply_rule2_no_flag_for_run_of_seven():
    center = 0.0
    vals = np.array([1.0] * 7 + [-1.0])
    flags = apply_rule2(vals, center)
    assert flags == []


def test_apply_rule3_flags_sixth_in_trend():
    # 6 strictly increasing points
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 0.0])
    flags = apply_rule3(vals)
    assert 5 in flags   # 6th point (index 5) completes the increasing run


def test_apply_rule3_no_flag_for_five_points():
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    flags = apply_rule3(vals)
    assert flags == []


def test_apply_rule4_flags_two_of_three_beyond_2sigma():
    center, sigma = 0.0, 1.0
    # Points at indices 0, 1, 2: two of three are above center+2sigma
    vals = np.array([2.5, 2.5, 0.0])   # indices 0 and 1 beyond 2σ
    flags = apply_rule4(vals, center, sigma)
    assert 2 in flags


def test_apply_all_rules_integrates_all_four():
    # Construct a series that fires rule 1 at index 0
    center, sigma = 0.0, 1.0
    ucl = center + 3 * sigma
    lcl = center - 3 * sigma
    vals = np.array([4.0] + [0.0] * 9)  # index 0 beyond UCL
    violations = apply_all_rules(vals, center, ucl, lcl, sigma)
    rule_nums = [r for _, r in violations]
    assert 1 in rule_nums


# ── Part C: Anomaly Detection ──────────────────────────────────────────────────

def test_isolation_forest_output_shapes():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((100, 5))
    _, scores, preds = train_isolation_forest(X, contamination=0.1)
    assert scores.shape == (100,)
    assert preds.shape == (100,)
    assert set(np.unique(preds)).issubset({-1, 1})


def test_isolation_forest_contamination_respected():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((200, 3))
    contamination = 0.05
    _, _, preds = train_isolation_forest(X, contamination=contamination)
    n_anomalies = int((preds == -1).sum())
    expected = int(200 * contamination)
    assert abs(n_anomalies - expected) <= 2  # allow rounding tolerance


def test_build_monthly_summary_aggregates_correctly():
    df = pd.DataFrame(
        {
            "_id": range(6),
            "_timestamp": pd.to_datetime(
                ["2008-01-10", "2008-01-15", "2008-02-01",
                 "2008-02-05", "2008-02-10", "2008-03-01"]
            ),
            "_label": [-1] * 6,
        }
    )
    preds = np.array([1, -1, 1, -1, 1, -1])  # alternating normal/anomaly
    summary = build_monthly_summary(df, preds)
    assert set(summary["month"]) == {"2008-01", "2008-02", "2008-03"}
    jan = summary[summary["month"] == "2008-01"].iloc[0]
    assert jan["total_rows"] == 2
    assert jan["anomaly_count"] == 1


# ── Part D: Yield Analysis ────────────────────────────────────────────────────

def test_prepare_xy_maps_labels_correctly():
    df = _make_df(sensor_0=[1.0, 2.0, 3.0])
    df["_label"] = [-1, 1, -1]   # pass, fail, pass
    X, y = prepare_xy(df, ["sensor_0"])
    assert list(y) == [0, 1, 0]
    assert X.shape == (3, 1)


def test_prepare_xy_fills_nan_with_median():
    df = _make_df(sensor_0=[1.0, float("nan"), 3.0])
    X, y = prepare_xy(df, ["sensor_0"])
    # median of [1.0, 3.0] = 2.0
    assert X["sensor_0"].iloc[1] == pytest.approx(2.0)


def test_build_importance_df_is_sorted_descending():
    from sklearn.ensemble import RandomForestClassifier

    rng = np.random.default_rng(1)
    X = pd.DataFrame(rng.random((50, 3)), columns=["s0", "s1", "s2"])
    y = pd.Series((rng.random(50) > 0.5).astype(int))
    model = RandomForestClassifier(n_estimators=10, random_state=1)
    model.fit(X, y)

    imp_df = build_importance_df(model, ["s0", "s1", "s2"], mi_scores={})
    scores = imp_df["importance_score"].tolist()
    assert scores == sorted(scores, reverse=True)
    assert list(imp_df["rank"]) == [1, 2, 3]
