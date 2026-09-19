"""Smoke tests — import checks and basic sanity. No DB or data files required."""
import importlib
import pytest


@pytest.mark.parametrize("module", [
    "pandas", "numpy", "sklearn", "sqlalchemy",
    "psycopg2", "xgboost", "shap", "imblearn",
    "matplotlib",
])
def test_import(module):
    importlib.import_module(module)


def test_pipeline_ingest_load_importable():
    from pipeline.ingest import load_secom  # noqa: F401


def test_pipeline_ingest_profile_importable():
    from pipeline.ingest import profile_secom  # noqa: F401


def test_pipeline_transform_importable():
    from pipeline.transform import clean_features  # noqa: F401


def test_pipeline_model_importable():
    from pipeline.model import train  # noqa: F401


def test_scripts_generate_erd_importable():
    from scripts import generate_erd  # noqa: F401


# ── unit tests for pure-logic helpers ─────────────────────────────────────────

def test_row_to_json_handles_nan():
    import json
    import numpy as np
    import pandas as pd
    from pipeline.ingest.load_secom import _row_to_json

    sensor_cols = ["sensor_0", "sensor_1", "sensor_2"]
    row = pd.Series({"sensor_0": 1.5, "sensor_1": float("nan"), "sensor_2": 0.0})

    result = json.loads(_row_to_json(row, sensor_cols))

    assert result["sensor_0"] == pytest.approx(1.5)
    assert result["sensor_1"] is None
    assert result["sensor_2"] == pytest.approx(0.0)


def test_row_to_json_all_null():
    import json
    import pandas as pd
    from pipeline.ingest.load_secom import _row_to_json

    sensor_cols = ["sensor_0", "sensor_1"]
    row = pd.Series({"sensor_0": float("nan"), "sensor_1": float("nan")})

    result = json.loads(_row_to_json(row, sensor_cols))
    assert result["sensor_0"] is None
    assert result["sensor_1"] is None


def test_bar_helper():
    from pipeline.ingest.profile_secom import _bar

    b0   = _bar(0)
    b100 = _bar(100)
    b50  = _bar(50)

    assert "█" not in b0
    assert "░" not in b100
    assert "█" in b50 and "░" in b50
