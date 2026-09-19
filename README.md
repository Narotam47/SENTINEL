# SENTINEL
### Manufacturing Process Monitoring & Yield Analytics

> A production-grade data engineering and ML pipeline built on the UCI SECOM semiconductor manufacturing dataset. Demonstrates end-to-end ownership of data ingestion, feature engineering, predictive modeling, and real-time operational dashboards — the core skills of a Technical Program Manager in hardware/silicon development.

---

## Purpose

Semiconductor fabs run thousands of sensors per wafer. A single undetected process drift can yield-kill an entire lot. SENTINEL simulates the analytics infrastructure a TPM would oversee to:

1. Ingest raw sensor telemetry and yield labels into a structured data store
2. Clean, impute, and engineer predictive features from high-dimensional, sparse data
3. Train a binary classifier (pass / fail) to surface at-risk lots before final test
4. Surface yield rate, failure trends, and model confidence on live Grafana dashboards

---

## Architecture

```
Raw CSV files (SECOM)
        │
        ▼
┌───────────────────┐
│  Ingest Pipeline  │  Python / Pandas → PostgreSQL (secom_raw)
└───────────────────┘
        │
        ▼
┌───────────────────┐
│ Transform Pipeline│  Imputation, variance filtering, feature engineering
│                   │  → secom_features
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Model Pipeline   │  Scikit-learn / XGBoost classifier
│                   │  → model_runs, predictions
└───────────────────┘
        │
        ▼
┌───────────────────┐
│     Grafana       │  Dashboards reading live from PostgreSQL
└───────────────────┘
```

**Stack:** Python 3.11 · PostgreSQL 15 · Grafana 10 · Docker · Scikit-learn · XGBoost · SHAP

---

## Database Schema

| Table | Description |
|---|---|
| `secom_raw` | Raw sensor readings + pass/fail label from SECOM CSV |
| `secom_features` | Cleaned, imputed, engineered features (post-transform) |
| `model_runs` | Metadata for each training run (AUC, F1, params) |
| `predictions` | Per-row model scores (used for drift monitoring) |
| `yield_metrics` | Pre-aggregated yield rates by time window for dashboards |

Schema lives in [`db/migrations/001_initial_schema.sql`](db/migrations/001_initial_schema.sql) and is applied automatically on first `docker compose up`.

---

## Dataset Setup

**Download the SECOM dataset from the UCI Machine Learning Repository:**

1. Go to: `https://archive.ics.uci.edu/dataset/179/secom`
2. Click **Download** — you will get a ZIP file
3. Extract and place the two files here:

```
SENTINEL/
└── data/
    └── raw/
        ├── secom.data          ← 1567 rows × 590 sensor columns (space-separated, NaN = "NaN")
        └── secom_labels.data   ← 1567 rows × 2 columns: label (-1/1), timestamp
```

The files are plain text. Do **not** rename them. They are git-ignored and never committed.

---

## Setup Instructions

### Prerequisites
- Docker Desktop ≥ 4.x (running)
- Python 3.11+
- `make` (comes with macOS Xcode tools)

### 1. Clone and configure

```bash
git clone <repo-url> SENTINEL
cd SENTINEL
cp .env.example .env   # edit if you change any passwords
```

### 2. Start the stack

```bash
make up
```

Starts PostgreSQL on `:5432` and Grafana on `:3000`. The SQL schema is applied automatically.

### 3. Set up Python environment

```bash
make setup-python
source .venv/bin/activate
```

### 4. Verify everything is healthy

```bash
make status
# or for a deeper check:
python scripts/check_env.py
```

### 5. Place the dataset, then ingest

```bash
# After placing secom.data and secom_labels.data in data/raw/
make ingest
```

---

## Running the Full Pipeline

```bash
make ingest      # Phase 1: raw data → PostgreSQL
make transform   # Phase 2: cleaning + feature engineering
make train       # Phase 3: model training + predictions
```

---

## Grafana Dashboard Guide

1. Open `http://localhost:3000` → login: `admin / sentinel_grafana`
2. Navigate to **Dashboards → SENTINEL**
3. Available panels:
   - **Yield Rate Over Time** — rolling pass rate by day/week
   - **Sensor Heatmap** — missing data and variance by sensor column
   - **Failure Probability Distribution** — model score histogram
   - **Top Predictive Features** — SHAP-ranked feature importance
   - **Prediction vs Actual** — confusion matrix and precision/recall over time

---

## Project Phases

| Phase | Description | Status |
|---|---|---|
| 0 | Environment & skeleton | ✅ Done |
| 1 | Data ingestion pipeline | ⬜ Next |
| 2 | Feature engineering | ⬜ Planned |
| 3 | ML model training | ⬜ Planned |
| 4 | Grafana dashboards | ⬜ Planned |
| 5 | Polish & documentation | ⬜ Planned |

---

## Repository Structure

```
SENTINEL/
├── data/
│   ├── raw/            ← SECOM source files (git-ignored)
│   ├── processed/      ← Intermediate outputs (git-ignored)
│   └── exports/        ← Reports and exports
├── db/
│   └── migrations/     ← SQL schema files (applied on container init)
├── grafana/
│   ├── dashboards/     ← Dashboard JSON definitions
│   └── provisioning/   ← Auto-provisioned datasource + dashboard config
├── notebooks/          ← EDA and exploratory work
├── pipeline/
│   ├── ingest/         ← SECOM CSV → PostgreSQL
│   ├── transform/      ← Cleaning and feature engineering
│   ├── features/       ← Feature store utilities
│   └── model/          ← Training, evaluation, prediction
├── scripts/            ← Utility scripts (env check, exports)
├── tests/              ← Pytest suite
├── .env.example        ← Environment variable template
├── docker-compose.yml  ← PostgreSQL + Grafana services
├── Makefile            ← One-command operations
└── requirements.txt    ← Python dependencies
```

---

*Built by Yash — portfolio project for Apple Technical Program Manager internship application.*
