"""
Phase 2 — HTML Data Quality Report Generator.

Queries the latest validation run from PostgreSQL and renders a standalone
HTML report to data/exports/data_quality_report.html.

Usage:
    python scripts/generate_quality_report.py
    make quality-report
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

ROOT    = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "data" / "exports"


# ── DB connection ─────────────────────────────────────────────────────────────

def _get_conn():
    try:
        return psycopg2.connect(
            host     = os.getenv("POSTGRES_HOST",     "localhost"),
            port     = int(os.getenv("POSTGRES_PORT", "5433")),
            dbname   = os.getenv("POSTGRES_DB",       "sentinel_db"),
            user     = os.getenv("POSTGRES_USER",     "sentinel"),
            password = os.getenv("POSTGRES_PASSWORD", "sentinel_pass"),
        )
    except psycopg2.OperationalError as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}")
        print("Run: make up")
        sys.exit(1)


# ── data queries ──────────────────────────────────────────────────────────────

def fetch_latest_run(conn) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM validation_runs ORDER BY validated_at DESC LIMIT 1"
        )
        return cur.fetchone()


def fetch_batch_quality(conn, run_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM data_quality WHERE validation_run_id = %s "
            "ORDER BY quality_score ASC",
            (run_id,),
        )
        return cur.fetchall()


def fetch_sensor_quality(conn, run_id: int, limit: int = None) -> list[dict]:
    sql = (
        "SELECT * FROM sensor_quality WHERE validation_run_id = %s "
        "ORDER BY quality_score ASC"
    )
    params = [run_id]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_rule_summary(conn, run_id: int) -> dict:
    """Aggregate per-rule stats across all sensors for the given run."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                             AS total_sensors,
                SUM(CASE WHEN missing_pct = 0    THEN 1 ELSE 0 END) AS sensors_no_missing,
                SUM(CASE WHEN missing_pct = 100  THEN 1 ELSE 0 END) AS sensors_dead,
                SUM(CASE WHEN missing_pct > 50
                          AND missing_pct < 100  THEN 1 ELSE 0 END) AS sensors_high_missing,
                SUM(CASE WHEN oor_pct > 0        THEN 1 ELSE 0 END) AS sensors_with_oor,
                SUM(CASE WHEN is_constant        THEN 1 ELSE 0 END) AS sensors_constant,
                AVG(missing_pct)                     AS avg_missing_pct,
                AVG(oor_pct)                         AS avg_oor_pct,
                AVG(quality_score)                   AS avg_quality_score
            FROM sensor_quality
            WHERE validation_run_id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
    keys = [
        "total_sensors", "sensors_no_missing", "sensors_dead",
        "sensors_high_missing", "sensors_with_oor", "sensors_constant",
        "avg_missing_pct", "avg_oor_pct", "avg_quality_score",
    ]
    return dict(zip(keys, row)) if row else {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _score_color(score: float) -> str:
    if score is None:
        return "#888"
    if score >= 90:
        return "#22c55e"   # green
    if score >= 75:
        return "#84cc16"   # lime
    if score >= 60:
        return "#f59e0b"   # amber
    return "#ef4444"       # red


def _score_badge(score: float) -> str:
    color = _score_color(score)
    label = ("EXCELLENT" if score >= 90
             else "GOOD"  if score >= 75
             else "POOR"  if score >= 60
             else "BAD")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:0.8em;font-weight:700;">{label}</span>'
    )


def _pct_bar(pct: float, color: str = "#ef4444", width: int = 80) -> str:
    filled = min(int(pct / 100 * width), width)
    return (
        f'<div style="background:#e5e7eb;border-radius:3px;height:8px;width:{width}px;'
        f'display:inline-block;vertical-align:middle;">'
        f'<div style="background:{color};width:{filled}px;height:8px;border-radius:3px;"></div>'
        f'</div>'
    )


def _f(val, fmt=".2f") -> str:
    if val is None:
        return "—"
    try:
        return format(float(val), fmt)
    except (TypeError, ValueError):
        return str(val)


# ── HTML builder ──────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f0f4f8;
    color: #1e293b;
    font-size: 14px;
    line-height: 1.5;
    padding: 0 0 60px;
}
header {
    background: linear-gradient(135deg, #1a3a5c 0%, #0f2040 100%);
    color: #fff;
    padding: 32px 40px 28px;
}
header h1 { font-size: 1.8em; font-weight: 800; letter-spacing: -0.5px; }
header .subtitle { color: #94a3b8; font-size: 0.9em; margin-top: 4px; }
.container { max-width: 1100px; margin: 0 auto; padding: 0 24px; }
.section { margin-top: 32px; }
.section-title {
    font-size: 1.05em; font-weight: 700; color: #1a3a5c;
    border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; margin-bottom: 16px;
}
.cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }
.card {
    background: #fff; border-radius: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
    padding: 20px 24px; flex: 1; min-width: 160px;
}
.card .card-value { font-size: 2em; font-weight: 800; line-height: 1.1; }
.card .card-label { color: #64748b; font-size: 0.82em; margin-top: 4px; }
.score-card .card-value { font-size: 3em; }
table {
    width: 100%; border-collapse: collapse;
    background: #fff; border-radius: 10px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow: hidden;
}
th {
    background: #1a3a5c; color: #e2e8f0;
    padding: 10px 14px; text-align: left;
    font-size: 0.8em; font-weight: 600; letter-spacing: 0.4px;
    text-transform: uppercase;
}
td { padding: 9px 14px; border-bottom: 1px solid #f1f5f9; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f8fafc; }
.tag {
    display: inline-block; border-radius: 4px;
    padding: 1px 7px; font-size: 0.78em; font-weight: 700;
}
.tag-yes { background: #fee2e2; color: #dc2626; }
.tag-no  { background: #dcfce7; color: #16a34a; }
.mono { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.85em; }
.warn { color: #d97706; }
.good { color: #16a34a; }
.bad  { color: #dc2626; }
footer {
    margin-top: 48px; text-align: center;
    color: #94a3b8; font-size: 0.8em;
}
"""


def _sensor_table(sensors: list[dict], title_suffix: str = "") -> str:
    rows_html = ""
    for s in sensors:
        score = float(s["quality_score"] or 0)
        color = _score_color(score)
        miss  = float(s["missing_pct"] or 0)
        oor   = float(s["oor_pct"]     or 0)
        const = s["is_constant"]
        rows_html += (
            f"<tr>"
            f"<td class='mono'>{s['sensor_name']}</td>"
            f"<td><span style='color:{color};font-weight:700;'>{_f(score)}</span> "
            f"{_pct_bar(score, color)}</td>"
            f"<td>{_f(miss)}% {_pct_bar(miss)}</td>"
            f"<td>{_f(oor)}% {_pct_bar(oor, '#f59e0b')}</td>"
            f"<td><span class='tag {'tag-yes' if const else 'tag-no'}'>"
            f"{'YES' if const else 'NO'}</span></td>"
            f"</tr>"
        )
    return f"""
    <div class="section">
      <div class="section-title">Sensor Quality — {title_suffix}</div>
      <table>
        <tr>
          <th>Sensor</th><th>Quality Score</th>
          <th>Missing %</th><th>Out-of-Range %</th><th>Constant?</th>
        </tr>
        {rows_html}
      </table>
    </div>
    """


def build_html(
    run: dict,
    batches: list[dict],
    worst_sensors: list[dict],
    rule_summary: dict,
    generated_at: datetime,
) -> str:
    b = batches[0] if batches else {}
    overall = float(run.get("overall_quality_score") or 0)
    score_color = _score_color(overall)

    # ── summary cards ────────────────────────────────────────────────────────
    n_rows     = int(b.get("total_rows", 0))
    n_sensors  = int(run.get("n_sensors", 0))
    avg_miss   = float(rule_summary.get("avg_missing_pct") or 0)
    n_const    = int(rule_summary.get("sensors_constant") or 0)
    n_dead     = int(rule_summary.get("sensors_dead") or 0)
    n_oor      = int(rule_summary.get("sensors_with_oor") or 0)
    dup_count  = int(b.get("dup_timestamp_count", 0))

    cards_html = f"""
    <div class="cards">
      <div class="card score-card">
        <div class="card-value" style="color:{score_color};">{overall:.1f}</div>
        <div class="card-label">Overall Quality Score (0–100)</div>
        <div style="margin-top:8px;">{_score_badge(overall)}</div>
      </div>
      <div class="card">
        <div class="card-value">{n_rows:,}</div>
        <div class="card-label">Total Rows Validated</div>
      </div>
      <div class="card">
        <div class="card-value">{n_sensors:,}</div>
        <div class="card-label">Total Sensors</div>
      </div>
      <div class="card">
        <div class="card-value {'warn' if avg_miss > 5 else 'good'}">{avg_miss:.1f}%</div>
        <div class="card-label">Avg Sensor Missing Rate</div>
      </div>
    </div>
    """

    # ── rule breakdown table ─────────────────────────────────────────────────
    miss_cell = float(b.get("missing_cell_pct") or 0)
    oor_row   = float(b.get("oor_row_pct")      or 0)

    rule_rows = [
        ("Missing Values",
         f"{miss_cell:.2f}% of all sensor cells are NULL",
         miss_cell == 0),
        ("Out-of-Range Readings",
         f"{oor_row:.2f}% of rows contain at least one reading beyond mean ± 3σ",
         oor_row < 5),
        ("Duplicate Timestamps",
         f"{dup_count} row(s) share a timestamp with another row",
         dup_count == 0),
        ("Constant Sensors",
         f"{n_const} sensor(s) have zero variance (uninformative)",
         n_const == 0),
        ("Dead Sensors (100% missing)",
         f"{n_dead} sensor(s) have no readings at all",
         n_dead == 0),
        ("Sensors with OOR readings",
         f"{n_oor} sensor(s) have at least one out-of-range reading",
         n_oor == 0),
    ]
    rule_rows_html = ""
    for rule, detail, is_ok in rule_rows:
        status_html = (
            "<span class='tag tag-no'>PASS ✓</span>"
            if is_ok
            else "<span class='tag tag-yes'>FLAG ⚠</span>"
        )
        rule_rows_html += (
            f"<tr><td><strong>{rule}</strong></td>"
            f"<td>{detail}</td><td>{status_html}</td></tr>"
        )

    rule_table = f"""
    <div class="section">
      <div class="section-title">Validation Rule Results</div>
      <table>
        <tr><th>Rule</th><th>Finding</th><th>Status</th></tr>
        {rule_rows_html}
      </table>
    </div>
    """

    # ── batch table ──────────────────────────────────────────────────────────
    batch_rows_html = ""
    for bt in batches:
        score = float(bt.get("quality_score") or 0)
        color = _score_color(score)
        batch_rows_html += (
            f"<tr>"
            f"<td class='mono' style='font-size:0.82em;'>{bt['batch_id']}</td>"
            f"<td>{bt['total_rows']:,}</td>"
            f"<td>{_f(bt['missing_cell_pct'])}%</td>"
            f"<td>{_f(bt['oor_row_pct'])}%</td>"
            f"<td>{bt['dup_timestamp_count']}</td>"
            f"<td>{bt['constant_sensor_count']}</td>"
            f"<td><span style='color:{color};font-weight:700;'>{_f(score)}</span> "
            f"{_score_badge(score)}</td>"
            f"</tr>"
        )
    batch_table = f"""
    <div class="section">
      <div class="section-title">Batch Quality</div>
      <table>
        <tr>
          <th>Batch ID</th><th>Rows</th><th>Missing%</th>
          <th>OOR Row%</th><th>Dup TS</th><th>Const Sensors</th>
          <th>Quality Score</th>
        </tr>
        {batch_rows_html}
      </table>
    </div>
    """

    # ── assemble ─────────────────────────────────────────────────────────────
    run_id_short = run.get("run_id", "")[:16] + "…"
    ts_str = generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    val_ts = run.get("validated_at")
    val_ts_str = val_ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(val_ts, "strftime") else str(val_ts)

    worst_sensor_section = _sensor_table(worst_sensors, "Top 10 Worst (lowest score)")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SENTINEL — Data Quality Report</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="container">
    <h1>SENTINEL &mdash; Data Quality Report</h1>
    <div class="subtitle">
      Manufacturing Process Monitoring &bull;
      Validation run: <strong>{run_id_short}</strong> &bull;
      Validated at: {val_ts_str} &bull;
      Report generated: {ts_str}
    </div>
  </div>
</header>

<div class="container">
  <div class="section">
    <div class="section-title">Executive Summary</div>
    {cards_html}
  </div>

  {rule_table}
  {batch_table}
  {worst_sensor_section}
</div>

<footer>
  <div class="container">
    SENTINEL &mdash; Apple TPM Portfolio Project &bull;
    Generated by <code>scripts/generate_quality_report.py</code> &bull;
    {ts_str}
  </div>
</footer>
</body>
</html>
"""


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    EXPORTS.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()

    run = fetch_latest_run(conn)
    if not run:
        print("No validation runs found in DB.")
        print("Run: make validate")
        conn.close()
        sys.exit(1)

    run_pk        = run["id"]
    batches       = fetch_batch_quality(conn, run_pk)
    worst_sensors = fetch_sensor_quality(conn, run_pk, limit=10)
    rule_summary  = fetch_rule_summary(conn, run_pk)
    conn.close()

    html = build_html(
        run           = dict(run),
        batches       = [dict(b) for b in batches],
        worst_sensors = [dict(s) for s in worst_sensors],
        rule_summary  = rule_summary,
        generated_at  = datetime.utcnow(),
    )

    out_path = EXPORTS / "data_quality_report.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Report saved → {out_path}")
    print(f"Open with:    open {out_path}")


if __name__ == "__main__":
    main()
