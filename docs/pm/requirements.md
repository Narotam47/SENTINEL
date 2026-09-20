# SENTINEL — Requirements Document

**Project:** SENTINEL — Manufacturing Process Monitoring & Yield Analytics  
**Version:** 1.0  
**Author:** Yash Narotam  
**Date:** Sep 20, 2026

---

## 1. Functional Requirements

### 1.1 Data Ingestion

| ID | Requirement | Priority | Acceptance Criterion | Phase |
|----|-------------|----------|----------------------|-------|
| FR-001 | The system SHALL ingest the SECOM dataset (1,567 rows × 590 sensors + binary label) from raw CSV files into PostgreSQL. | Must-have | `SELECT COUNT(*) FROM secom_raw` = 1,567 after `make ingest` | P1 |
| FR-002 | Every ingested row SHALL carry a `batch_id` (UUID), `source_file`, and `ingest_timestamp` for full audit traceability. | Must-have | All three columns are non-NULL for every row in `secom_raw` | P1 |
| FR-003 | The ingest pipeline SHALL be idempotent: re-running `make ingest` replaces all records without creating duplicates. | Must-have | `TRUNCATE … CASCADE` on `secom_raw` before each ingest; row count = 1,567 regardless of how many times run | P1 |
| FR-004 | Sensor readings SHALL be stored as JSONB to support 590-wide sparse data without 590 nullable columns. | Must-have | `SELECT features->'sensor_0' FROM secom_raw LIMIT 1` returns a value | P1 |

### 1.2 Data Integrity Validation

| ID | Requirement | Priority | Acceptance Criterion | Phase |
|----|-------------|----------|----------------------|-------|
| FR-005 | The validation engine SHALL check four data quality dimensions: missing values, out-of-range readings (μ±3σ), duplicate timestamps, and constant (zero-variance) sensors. | Must-have | All four check functions return correct results on synthetic test DataFrames (27 unit tests) | P2 |
| FR-006 | The system SHALL compute a quality score from 0–100 for every batch and every sensor, using a documented weighted penalty formula. | Must-have | Quality scores written to `data_quality` and `sensor_quality` tables; scores in [0, 100] range | P2 |
| FR-007 | The system SHALL generate a standalone HTML quality report readable without installing any additional tools. | Must-have | `data/exports/data_quality_report.html` opens in a browser and shows quality scores and sensor breakdown | P2 |

### 1.3 Analytics

| ID | Requirement | Priority | Acceptance Criterion | Phase |
|----|-------------|----------|----------------------|-------|
| FR-008 | The feature selection pipeline SHALL reduce 590 sensors to a smaller set by removing high-missing, constant, and highly correlated sensors, then ranking survivors by mutual information. | Must-have | `selected_features.csv` exists; fewer than 590 sensors; all removed sensors documented in console output | P3 |
| FR-009 | The system SHALL apply I-MR Statistical Process Control charts to the top-10 yield-correlated sensors and flag all four Western Electric rule violations in the `spc_flags` table. | Must-have | `spc_flags` is non-empty after `make spc`; rule_number values ∈ {1, 2, 3, 4} | P3 |
| FR-010 | The system SHALL train an unsupervised Isolation Forest on all selected sensor features and write an `anomaly_score` and `is_anomaly` flag to every row in `secom_raw`. | Must-have | Zero NULL values for `anomaly_score` and `is_anomaly` in `secom_raw` after `make anomaly` | P3 |
| FR-011 | The system SHALL train a Random Forest classifier (handling class imbalance) and write the top-10 feature importances to the `yield_drivers` table. | Must-have | `yield_drivers` has exactly 10 rows after `make yield-analysis`; importances sum to ≈1.0 | P3 |

### 1.4 Dashboard

| ID | Requirement | Priority | Acceptance Criterion | Phase |
|----|-------------|----------|----------------------|-------|
| FR-012 | The Grafana dashboard SHALL be provisioned entirely from config files; no manual setup steps SHALL be required after `docker compose up`. | Must-have | `make dashboard-check` reports 6 panels and a connected datasource without any user clicking in the Grafana UI | P4 |
| FR-013 | The dashboard SHALL include at minimum: yield trend over time, data quality score, anomaly flagging, sensor health ranking, and SPC violation table. | Must-have | All 6 panels in `sentinel_overview.json` return data (not "No data") when the full pipeline has been run | P4 |

---

## 2. Non-Functional Requirements

| ID | Requirement | Target | Measurement |
|----|-------------|--------|-------------|
| NFR-001 | **Reproducibility** — Any team member SHALL be able to reproduce the full system from a `git clone` in under 15 minutes. | ≤15 min end-to-end | Time from `git clone` to `make dashboard-check` showing READY |
| NFR-002 | **Test coverage** — All pure business logic functions SHALL have unit tests. DB-dependent and UI-dependent code is exempt. | 100% of pure functions | 67 tests across 3 modules; all pass with no DB or Docker required |
| NFR-003 | **Idempotency** — Every pipeline step SHALL be safely re-runnable without corrupting state. | Zero data duplication on re-run | TRUNCATE/INSERT pattern in ingest; IF NOT EXISTS in all migrations |
| NFR-004 | **Portability** — The system SHALL run on macOS and Linux without OS-specific configuration. | Zero OS-specific code | Docker handles runtime isolation; Makefile uses POSIX commands |
| NFR-005 | **Auditability** — Every row ingested SHALL carry a batch identifier linking it to the ingest event that created it. | 0 NULL batch_ids | `SELECT COUNT(*) FROM secom_raw WHERE batch_id IS NULL` = 0 |

---

## 3. Out of Scope

The following items were explicitly considered and deferred to avoid scope creep. They are documented here so a future phase can pick them up clearly:

| Item | Rationale |
|------|-----------|
| Real-time / streaming ingestion (Kafka, Kinesis) | SECOM is a static historical dataset; streaming would require a fundamentally different source system |
| SHAP explainability values | `shap` is installed in `requirements.txt`; implementation deferred to Phase 6 |
| XGBoost model | `xgboost` installed; deferred — RandomForest provides sufficient feature importance for a portfolio |
| SMOTE oversampling | Deferred; `class_weight='balanced'` provides sufficient imbalance correction for a portfolio |
| Grafana alerting (email / Slack) | Alerting requires external notification channels; out of scope for local development |
| Multi-user auth / RBAC | Single-user local deployment; enterprise auth out of scope |
| CI/CD pipeline (GitHub Actions) | `.github/workflows/` scaffold exists; implementation deferred to Phase 6 |
| Data drift monitoring | Suitable for a Phase 6 using Evidently or similar |
| Custom Grafana plugin | Standard Grafana panels sufficient; plugin development disproportionate to scope |

---

## 4. Acceptance Criteria by Phase

### Phase 0
- [ ] `make up` starts PostgreSQL and Grafana with no errors  
- [ ] `make test` executes (0 tests, 0 failures — suite scaffold only)  
- [ ] `make down` stops all containers cleanly  

### Phase 1
- [ ] `make ingest` completes without error  
- [ ] `SELECT COUNT(*) FROM secom_raw` = 1,567  
- [ ] Every row has non-NULL `batch_id`, `source_file`, `ingest_timestamp`  
- [ ] `docs/erd.png` generated by `make erd`  
- [ ] 17 tests passing (`test_smoke.py`)  

### Phase 2
- [ ] `make validate` completes; `validation_runs` has ≥1 row  
- [ ] `quality_score` ∈ [0, 100] for all rows in `data_quality` and `sensor_quality`  
- [ ] `make quality-report` generates `data/exports/data_quality_report.html`  
- [ ] 44 tests passing (smoke + validation)  

### Phase 3
- [ ] `make feature-select` — `selected_features.csv` exists; `secom_features` populated  
- [ ] `make spc` — `spc_flags` non-empty; rule_number ∈ {1, 2, 3, 4}  
- [ ] `make anomaly` — 0 NULL values for `anomaly_score` in `secom_raw`  
- [ ] `make yield-analysis` — `yield_drivers` has 10 rows; `yield_feature_importance.csv` exists  
- [ ] 67 tests passing  

### Phase 4
- [ ] `make dashboard-check` reports 6 panels and connected datasource  
- [ ] All 6 panels render with data (no "No data" state)  
- [ ] Dashboard reloads automatically after `docker compose restart grafana`  

### Phase 5
- [ ] `scripts/final_check.py` exits 0 and prints `SENTINEL READY`  
- [ ] All 6 PM documents committed to `docs/pm/`  
- [ ] `README.md` includes architecture diagram, setup instructions, Makefile reference  
