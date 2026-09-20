# SENTINEL — Work Breakdown Structure

**Project:** SENTINEL — Manufacturing Process Monitoring & Yield Analytics  
**Owner:** Yash Narotam  
**Duration:** 2 weeks (Sep 7–20, 2026)  
**Total estimated:** 46.0 h | **Total actual:** 51.5 h | **Variance:** +5.5 h (+12%)

Variance driven by: timestamp parsing bug in Phase 1 (+1.5 h), Grafana JSON debug loop in Phase 4 (+1.0 h), expanded SPC rule tests in Phase 3 (+0.5 h), README depth (+1.0 h).

---

## 1.0 Phase 0 — Environment & Skeleton

| ID | Task | Subtask | Est (h) | Act (h) | Δ |
|----|------|---------|---------|---------|---|
| 1.1 | Repository structure | Create directory tree, `.gitignore`, `README.md` stub | 0.5 | 0.5 | 0 |
| 1.2 | Docker Compose | `docker-compose.yml` — PostgreSQL 15 + Grafana 10; health-check config | 1.0 | 1.5 | +0.5 |
| 1.3 | Initial DB schema | `001_initial_schema.sql` — 5 tables with FK constraints | 1.0 | 1.0 | 0 |
| 1.4 | Makefile & tooling | All Make targets; `setup-python`; Python `.venv` scaffold | 0.5 | 1.0 | +0.5 |
| 1.5 | Python environment | `requirements.txt`; Python 3.13 compatibility baseline | 0.5 | 0.5 | 0 |
| | **Phase 0 total** | | **3.5** | **4.5** | **+1.0** |

---

## 2.0 Phase 1 — Data Layer (Ingest + Schema)

| ID | Task | Subtask | Est (h) | Act (h) | Δ |
|----|------|---------|---------|---------|---|
| 2.1 | SECOM profiling | `profile_secom.py` — shape, missing %, imbalance report | 1.0 | 1.5 | +0.5 |
| 2.2 | Ingest pipeline | `load_secom.py` — 3-token timestamp parse, NaN-safe JSON, bulk insert | 3.0 | 4.5 | +1.5 |
| 2.3 | Audit trail | `002_audit_columns.sql` — `batch_id`, `source_file`, `ingest_timestamp` | 0.5 | 0.5 | 0 |
| 2.4 | ERD generator | `generate_erd.py` — `information_schema` query → matplotlib → `docs/erd.png` | 1.0 | 1.0 | 0 |
| 2.5 | Unit tests | 17 tests: import smoke + `_row_to_json` + profiler helpers | 1.5 | 1.5 | 0 |
| | **Phase 1 total** | | **7.0** | **9.0** | **+2.0** |

*Root cause of +1.5 h on 2.2: SECOM labels file uses 3 whitespace-separated tokens (`label date time`); initial single-column parse silently misaligned all timestamps.*

---

## 3.0 Phase 2 — Data Integrity Layer

| ID | Task | Subtask | Est (h) | Act (h) | Δ |
|----|------|---------|---------|---------|---|
| 3.1 | Validation rules | 4 pure check functions: missing %, OOR (μ±3σ), dup timestamps, constant sensors | 2.0 | 2.0 | 0 |
| 3.2 | Quality scoring | Weighted penalty formula (0–100); per-batch and per-sensor scores | 1.0 | 1.0 | 0 |
| 3.3 | DB write | `003_data_quality.sql` — 3 tables; idempotent migration; psycopg2 write | 1.0 | 1.0 | 0 |
| 3.4 | HTML report | `generate_quality_report.py` — standalone HTML; colour-coded score badges | 1.5 | 2.0 | +0.5 |
| 3.5 | Unit tests | 27 pure tests: all 4 check functions, both score formulas, edge cases | 2.0 | 2.0 | 0 |
| | **Phase 2 total** | | **7.5** | **8.0** | **+0.5** |

---

## 4.0 Phase 3 — Analytics Layer

| ID | Task | Subtask | Est (h) | Act (h) | Δ |
|----|------|---------|---------|---------|---|
| 4.1 | Feature selection | 4-step pipeline: >40% missing → constant → corr >0.95 → MI ranking; writes CSV + `secom_features` | 2.5 | 3.0 | +0.5 |
| 4.2 | SPC / I-MR charts | 4 Western Electric rules; MR̄/d₂ σ estimate; writes `spc_flags`; migration 004 | 3.0 | 3.0 | 0 |
| 4.3 | Anomaly detection | `IsolationForest` contamination=0.07; updates `secom_raw`; monthly CSV | 1.5 | 1.5 | 0 |
| 4.4 | Yield correlation | `RandomForestClassifier` class_weight='balanced'; feature importances; `yield_drivers` | 2.0 | 2.0 | 0 |
| 4.5 | DB schema | `004_spc.sql` — `spc_flags`, `yield_drivers`, anomaly cols on `secom_raw` | 1.0 | 1.0 | 0 |
| 4.6 | Unit tests | 23 pure tests: feature selection steps, all 4 WE rules, Isolation Forest, RF | 2.0 | 2.0 | 0 |
| | **Phase 3 total** | | **12.0** | **12.5** | **+0.5** |

---

## 5.0 Phase 4 — Grafana Dashboard

| ID | Task | Subtask | Est (h) | Act (h) | Δ |
|----|------|---------|---------|---------|---|
| 5.1 | Provisioning | `sentinel.yml` dashboard provider + `postgres.yml` datasource; no-click setup | 1.0 | 1.0 | 0 |
| 5.2 | Dashboard JSON | 6-panel `sentinel_overview.json`: yield trend, quality stat, anomaly summary, sensor health, flagged readings, SPC events | 4.0 | 5.0 | +1.0 |
| 5.3 | Ops guide | `DASHBOARD.md` — plain-English panel descriptions, WE rule table, navigation tips | 1.0 | 1.0 | 0 |
| 5.4 | `dashboard-check` | Makefile target: Grafana health API + dashboard panel count + browser open | 0.5 | 0.5 | 0 |
| | **Phase 4 total** | | **6.5** | **7.5** | **+1.0** |

*Root cause of +1.0 h on 5.2: Grafana 10 `barchart` `xField` property requires explicit field name; default category-axis detection doesn't work with renamed SQL columns.*

---

## 6.0 Phase 5 — PM Layer & Repository Polish

| ID | Task | Subtask | Est (h) | Act (h) | Δ |
|----|------|---------|---------|---------|---|
| 6.1 | WBS | This document — hierarchical breakdown with estimated vs actual hours | 1.0 | 1.0 | 0 |
| 6.2 | Milestones | Milestone table + Mermaid Gantt chart | 0.5 | 0.5 | 0 |
| 6.3 | Risk register | 8 risks with P/I rating, mitigation, owner, status | 1.0 | 1.0 | 0 |
| 6.4 | Status reports | Week 1 and Week 2 engineering status updates | 1.0 | 1.0 | 0 |
| 6.5 | Requirements | FRs, NFRs, out-of-scope, acceptance criteria | 1.5 | 1.5 | 0 |
| 6.6 | README rewrite | Full architecture document with Mermaid diagram and setup guide | 2.0 | 3.0 | +1.0 |
| 6.7 | Code cleanup | Verify docstrings; remove debug prints; `.gitignore` audit | 1.0 | 1.0 | 0 |
| 6.8 | Final check script | `scripts/final_check.py` — 15-point system health verification | 1.0 | 1.0 | 0 |
| | **Phase 5 total** | | **9.0** | **10.0** | **+1.0** |

---

## Summary

| Phase | Description | Est (h) | Act (h) | Δ |
|-------|-------------|---------|---------|---|
| 0 | Environment & Skeleton | 3.5 | 4.5 | +1.0 |
| 1 | Data Layer | 7.0 | 9.0 | +2.0 |
| 2 | Data Integrity | 7.5 | 8.0 | +0.5 |
| 3 | Analytics | 12.0 | 12.5 | +0.5 |
| 4 | Dashboard | 6.5 | 7.5 | +1.0 |
| 5 | PM Layer & Polish | 9.0 | 10.0 | +1.0 |
| | **Total** | **45.5** | **51.5** | **+6.0 (+13%)** |

Variance within acceptable range for a greenfield project. Primary driver was initial SECOM data format research and Grafana 10 API differences from documentation.
