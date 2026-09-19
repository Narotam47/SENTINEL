# SENTINEL Dashboard Guide

> **For operations readers** — no Grafana experience required.
> Open the dashboard at **http://localhost:3000** (login: `admin` / `sentinel_grafana`).

---

## What the dashboard shows

The SENTINEL dashboard gives manufacturing ops a single-screen view of semiconductor wafer yield health. It pulls live data from the PostgreSQL database — every panel is a SQL query that runs automatically when you open the page.

---

## The five panels

### 1 · Yield Trend Over Time *(top-left, line chart)*

**What it shows:** The number of wafers that *passed* (green) or *failed* (red) the yield test each week, plotted over time.

**How to read it:** Normal operation looks like a wide green band above a flat, low red line. An upward spike in red or a downward dip in green is a *yield excursion* — the process is producing more scrap than usual and engineering should investigate.

**Data source:** `secom_raw` table — every wafer run, grouped by week.

---

### 2 · Data Quality Score *(top-right, coloured number)*

**What it shows:** A single score from 0 to 100 rating how clean and reliable the most recent sensor data collection was.

| Colour | Score | Meaning |
|--------|-------|---------|
| Green  | 90–100 | Data is trustworthy — proceed normally |
| Yellow | 75–89  | Mild issues (some missing readings); monitor sensors |
| Orange | 60–74  | Significant gaps or out-of-range values; investigate |
| Red    | < 60   | Data integrity problems; analytics may be unreliable |

Below the score you also see how many wafer runs and sensors were included in the latest check.

**Data source:** `validation_runs` table — results from `make validate`.

---

### Anomaly Summary *(top-right, stat tiles)*

**What it shows:** Quick-count of how many runs the anomaly-detection model flagged as unusual, and how many of those actually failed.

**How to read it:** If "Anomalies That Failed" is a large fraction of "Anomalies Flagged", the model is correctly identifying real failures early. If the counts diverge widely, the process has near-miss events that passed testing but were statistically abnormal — worth tracking before they become failures.

**Data source:** `secom_raw.is_anomaly` and `secom_raw.label` columns.

---

### 3 · Sensor Health: Lowest-Scoring Sensors *(middle-left, horizontal bar chart)*

**What it shows:** The 20 sensors with the lowest average quality scores, sorted worst-first (leftmost bar = worst sensor). Each bar's colour also signals severity: red → yellow → green.

**How to read it:** A short bar on the left means that sensor frequently delivers bad data — missing readings, values way outside its normal range, or a "stuck" constant value. These sensors are candidates for:
- Physical inspection and recalibration
- Increased maintenance frequency
- Replacement if quality remains low

**Data source:** `sensor_quality` table — per-sensor scores from `make validate`.

---

### 4 · Anomalous Sensor Readings *(middle-right, table)*

**What it shows:** A row-by-row list of every individual wafer run flagged as anomalous by the Isolation Forest model, including when it happened, how anomalous it was, and whether it actually failed yield testing.

**Column guide:**

| Column | Meaning |
|--------|---------|
| Batch ID | Which production batch the wafer came from |
| Timestamp | When the run was recorded |
| Anomaly Score | How abnormal the sensor readings were — more *negative* = more unusual |
| Yield Outcome | Whether the wafer actually passed or failed the final test |

**Key insight:** Runs shown as `pass` in this table are *near-misses* — the model flagged them as statistically unusual even though they passed. In a real fab, these would trigger an engineer review before the next batch.

**Data source:** `secom_raw` — rows where `is_anomaly = TRUE`.

---

### 5 · SPC Out-of-Control Events *(bottom, full-width table)*

**What it shows:** Every Western Electric rule violation detected across the top-10 yield-correlated sensors, sorted by rule severity (Rule 1 first).

**Understanding the rules:**

| Rule # | Colour | Meaning | Urgency |
|--------|--------|---------|---------|
| 1 | Red | A single reading shot past the 3-sigma limit | **Stop and investigate immediately** — the process has drifted out of control |
| 2 | Orange | 8+ consecutive readings all above or all below the process mean | **Elevated concern** — the process is shifted and not recovering |
| 3 | Yellow | 6+ consecutive readings all trending in one direction (always rising or always falling) | **Early warning** — the process is drifting before it hits the hard limit |
| 4 | Yellow | 2 of 3 consecutive readings beyond the 2-sigma line on the same side | **Early warning** — similar to Rule 3, catching drift sooner |

**Column guide:**

| Column | Meaning |
|--------|---------|
| Sensor | Which sensor fired the rule |
| Timestamp | When the event occurred in production |
| Rule # | Rule number (1 = most severe) |
| Rule Violated | Plain-English description of what the rule detected |
| Value | The actual sensor reading at the flagged point |
| Centre Line | The process mean (what "normal" looks like for this sensor) |
| UCL / LCL | Upper / Lower Control Limits — the 3-sigma boundaries |

**Data source:** `spc_flags` table — written by `make spc`.

---

## Navigating the dashboard

- **Time range** — use the date picker in the top-right corner. The default shows the full SECOM dataset (Jan–Jul 2008). Narrow it to zoom into a specific excursion.
- **Hover** — hovering over any chart shows exact values in a tooltip.
- **Sort tables** — click any column header to sort ascending or descending.
- **Filter tables** — the Anomalous Readings and SPC tables support column filtering: hover the column header and click the funnel icon.
- **Zoom a chart** — click and drag a region on any time-series chart to zoom into that window.

---

## How provisioning works

Grafana provisioning means the dashboard and data source are defined in YAML/JSON config files, not clicked together through the UI. When `docker compose up` starts the Grafana container, it reads:

```
grafana/provisioning/
  datasources/postgres.yml   → auto-connects PostgreSQL (no manual setup)
  dashboards/sentinel.yml    → tells Grafana to load dashboard JSON from disk
grafana/dashboards/
  sentinel_overview.json     → the dashboard definition itself
```

The result: every team member who runs `make up` gets the identical dashboard immediately, with no import steps. If you edit `sentinel_overview.json` and restart Grafana (or wait up to 30 seconds for auto-reload), the change appears for everyone.
