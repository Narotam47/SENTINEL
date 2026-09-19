"""Quick pre-flight check — verifies Docker services and DB schema are ready."""
import sys
import subprocess
import urllib.request


def check_postgres():
    result = subprocess.run(
        ["docker", "exec", "sentinel_postgres",
         "pg_isready", "-U", "sentinel", "-d", "sentinel_db"],
        capture_output=True, text=True
    )
    ok = result.returncode == 0
    print(f"  PostgreSQL : {'OK' if ok else 'FAIL'} — {result.stdout.strip()}")
    return ok


def check_grafana():
    try:
        with urllib.request.urlopen("http://localhost:3000/api/health", timeout=5) as r:
            ok = r.status == 200
    except Exception as e:
        ok = False
        print(f"  Grafana    : FAIL — {e}")
        return False
    print(f"  Grafana    : OK — HTTP {r.status}")
    return ok


def check_schema():
    result = subprocess.run(
        ["docker", "exec", "sentinel_postgres",
         "psql", "-U", "sentinel", "-d", "sentinel_db",
         "-c", "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"],
        capture_output=True, text=True
    )
    ok = "secom_raw" in result.stdout
    print(f"  DB schema  : {'OK — tables found' if ok else 'FAIL — tables missing'}")
    if not ok:
        print("    Tables found:", result.stdout.strip())
    return ok


if __name__ == "__main__":
    print("\nSENTINEL — Environment Check")
    print("=" * 40)
    results = [check_postgres(), check_grafana(), check_schema()]
    print()
    if all(results):
        print("All checks passed. Ready for Phase 1.")
    else:
        print("One or more checks failed. Run `make up` and retry.")
        sys.exit(1)
