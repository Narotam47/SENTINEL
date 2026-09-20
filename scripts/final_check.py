"""15-point system health verification for SENTINEL."""

import sys
import subprocess
from pathlib import Path

import psycopg2
import requests

DB_DSN = "host=localhost port=5432 dbname=sentinel_db user=sentinel password=sentinel_pass"
GRAFANA_BASE = "http://localhost:3000"
GRAFANA_AUTH = ("admin", "sentinel_grafana")
PROJECT_ROOT = Path(__file__).parent.parent

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"


def check(label: str, ok: bool, detail: str = "") -> bool:
    """Print one check result and return its pass/fail status."""
    icon = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon}  {label}{suffix}")
    return ok


def main() -> int:
    print("\nSENTINEL — System Health Check\n" + "=" * 40)
    results: list[bool] = []

    # ── Docker / network ────────────────────────────────────────────────────
    print("\n[1/4] Infrastructure")

    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = out.stdout.strip().splitlines()
        results.append(check("PostgreSQL container running",
                             "sentinel_postgres" in containers,
                             "sentinel_postgres"))
        results.append(check("Grafana container running",
                             "sentinel_grafana" in containers,
                             "sentinel_grafana"))
    except Exception as exc:
        results.append(check("PostgreSQL container running", False, str(exc)))
        results.append(check("Grafana container running", False, str(exc)))

    # ── Database ─────────────────────────────────────────────────────────────
    print("\n[2/4] Database")

    EXPECTED_TABLES = {
        "secom_raw": 1567,
        "secom_features": 1567,
        "data_quality": 1,
        "sensor_quality": 1,
        "validation_runs": 1,
        "spc_flags": 1,
        "yield_drivers": 10,
        "model_runs": 0,
        "predictions": 0,
        "yield_metrics": 0,
    }

    try:
        conn = psycopg2.connect(DB_DSN, connect_timeout=5)
        cur = conn.cursor()

        for table, min_rows in EXPECTED_TABLES.items():
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            ok = count >= min_rows
            results.append(check(
                f"Table {table!r} populated",
                ok,
                f"{count:,} rows" + (f" (expected ≥{min_rows})" if not ok else ""),
            ))

        # Check anomaly scores populated
        cur.execute("SELECT COUNT(*) FROM secom_raw WHERE anomaly_score IS NULL")
        null_anomaly = cur.fetchone()[0]
        results.append(check("anomaly_score fully populated",
                             null_anomaly == 0, f"{null_anomaly} NULLs"))

        conn.close()
    except Exception as exc:
        print(f"  \033[91m✗\033[0m  Could not connect to PostgreSQL: {exc}")
        for _ in EXPECTED_TABLES:
            results.append(False)
        results.append(False)

    # ── Export files ─────────────────────────────────────────────────────────
    print("\n[3/4] Export files")

    exports = [
        "data/exports/selected_features.csv",
        "data/exports/anomaly_summary.csv",
        "data/exports/yield_feature_importance.csv",
        "data/exports/yield_model_report.txt",
        "data/exports/data_quality_report.html",
    ]

    for rel in exports:
        path = PROJECT_ROOT / rel
        results.append(check(f"File {rel}", path.exists(),
                             "present" if path.exists() else "MISSING"))

    # ── Grafana ───────────────────────────────────────────────────────────────
    print("\n[4/4] Grafana")

    try:
        r = requests.get(f"{GRAFANA_BASE}/api/health", timeout=5)
        results.append(check("Grafana API reachable",
                             r.status_code == 200, r.json().get("database", "")))
    except Exception as exc:
        results.append(check("Grafana API reachable", False, str(exc)))

    try:
        r = requests.get(
            f"{GRAFANA_BASE}/api/dashboards/uid/sentinel-overview",
            auth=GRAFANA_AUTH, timeout=5,
        )
        ok = r.status_code == 200
        panel_count = len(r.json().get("dashboard", {}).get("panels", [])) if ok else 0
        results.append(check("Dashboard UID sentinel-overview exists",
                             ok and panel_count >= 6, f"{panel_count} panels"))
    except Exception as exc:
        results.append(check("Dashboard sentinel-overview exists", False, str(exc)))

    try:
        r = requests.get(
            f"{GRAFANA_BASE}/api/datasources/name/SENTINEL_PostgreSQL",
            auth=GRAFANA_AUTH, timeout=5,
        )
        results.append(check("PostgreSQL datasource provisioned",
                             r.status_code == 200,
                             r.json().get("url", "") if r.status_code == 200 else "not found"))
    except Exception as exc:
        results.append(check("PostgreSQL datasource provisioned", False, str(exc)))

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 40}")
    print(f"Checks passed: {passed}/{total}")

    if passed == total:
        print("\n\033[92m★  SENTINEL READY  ★\033[0m\n")
        return 0
    else:
        failed = total - passed
        print(f"\n\033[91m✗  SENTINEL NOT READY — {failed} check(s) failed\033[0m\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
