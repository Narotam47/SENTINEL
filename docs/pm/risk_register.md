# SENTINEL — Risk Register

**Project:** SENTINEL — Manufacturing Process Monitoring & Yield Analytics  
**Last updated:** Sep 20, 2026  

**Probability scale:** H = >60%  M = 20–60%  L = <20%  
**Impact scale:** H = blocks a milestone  M = delays >1 day or degrades quality  L = minor workaround needed

---

| Risk ID | Description | Category | Probability | Impact | Risk Score | Mitigation | Owner | Status |
|---------|-------------|----------|-------------|--------|------------|------------|-------|--------|
| R-001 | **High missing-value rate in sensor data** — SECOM has 5.4% missing cells overall; individual sensors reach 80%+ missing. If not handled, ML models train on biased feature sets and control charts show false positives. | Data Quality | H | H | **HH** | Step 1 of feature selection drops sensors with >40% missing before any ML. OOR check uses μ±3σ per sensor (not global), so NaN rows don't contaminate limits. IsolationForest and RandomForest both receive median-filled matrices. | Pipeline lead | ✅ CLOSED — mitigated in Phase 3 |
| R-002 | **Schema design locked before analytics requirements known** — migrations 001–003 were written in Phases 0–2 without full knowledge of what Phase 3 columns were needed, risking destructive re-migrations. | Technical | M | H | **MH** | All migrations use `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` (PostgreSQL 15 idempotent pattern). Migration 004 adds analytics columns without touching existing data. | DB architect | ✅ CLOSED — all migrations idempotent |
| R-003 | **Grafana datasource fails to connect after `docker compose up`** — wrong hostname (using `localhost` instead of Docker service name `sentinel_postgres`) is a common first-run failure that blocks all 6 panels. | Infrastructure | M | H | **MH** | Datasource provisioned via `postgres.yml` with `url: sentinel_postgres:5432` (Docker internal DNS). `make dashboard-check` validates connectivity via the Grafana API before user opens browser. | DevOps | ✅ CLOSED — connectivity verified |
| R-004 | **14:1 class imbalance renders yield model precision meaningless** — with only 104 fail records vs 1,463 pass, a naive classifier can achieve 93.4% accuracy by always predicting pass, making recall on failures effectively 0%. | ML / Data Science | H | M | **HM** | `RandomForestClassifier(class_weight='balanced')` upweights minority class. Stratified train/test split preserves class ratio in test set. Classification report includes per-class precision/recall rather than accuracy. Model results framed as "feature importances for yield analysis," not as a production predictor. | ML lead | ✅ CLOSED — mitigated in Phase 3D |
| R-005 | **Python 3.13 binary incompatibility with pinned package versions** — several ML packages (pandas, NumPy, scikit-learn) did not yet publish pre-built wheels for Python 3.13 at the versions commonly pinned in tutorials; source builds fail on Cython API changes. | Environment | M | H | **MH** | `requirements.txt` uses `>=` minimum-version bounds (not `==` pins) so pip selects the newest compatible wheel. All packages tested against Python 3.13.9. | DevOps | ✅ CLOSED — confirmed working in Phase 0 |
| R-006 | **Timeline slippage from debugging data ingestion** — the SECOM labels file encodes timestamps as 3 whitespace-separated tokens (`label date time`), not 2 columns as documentation implies. Misparse silently shifts all timestamps by one field. | Schedule | M | M | **MM** | Profiling step (`make profile`) validates row counts and timestamp range before ingest. Pipeline test `test_timestamp_parse` added to catch regressions. Issue discovered and resolved within same work session; no milestone impact beyond +1.5 h. | Pipeline lead | ✅ CLOSED — resolved in Phase 1 |
| R-007 | **Docker volume permission differences across macOS/Linux** — Grafana container running as UID 472 may fail to write to host-mounted volumes on Linux hosts with strict file permissions, blocking dashboard persistence. | Infrastructure | L | M | **LM** | Named volumes (`grafana_data`, `postgres_data`) are used for all persistent state rather than bind mounts for data. Dashboard JSON is provisioned from a bind-mounted read-only config path (`./grafana/provisioning`) — no write permission needed. | DevOps | ✅ CLOSED — verified on macOS; documented for Linux |
| R-008 | **Scope creep into real-time streaming or advanced explainability** — SHAP, XGBoost, SMOTE, and real-time Kafka ingestion were considered but not in scope. Accepting any one of these mid-sprint would have pushed the 2-week deadline. | Schedule / Scope | H | M | **HM** | Scope explicitly documented in `docs/pm/requirements.md` out-of-scope section. `requirements.txt` includes `shap` and `xgboost` as installed but unused — reserved for a Phase 6 if the project continues. Scope changes require explicit approval against the milestone schedule. | PM | ✅ CLOSED — scope held |

---

## Risk Summary

| Score | Count | Status |
|-------|-------|--------|
| HH (Critical) | 1 | All closed |
| MH (High) | 3 | All closed |
| HM (High) | 2 | All closed |
| MM (Medium) | 1 | All closed |
| LM (Low–Medium) | 1 | All closed |
| **Total** | **8** | **8/8 closed** |

All identified risks were mitigated before the corresponding phase milestone. No open risks remain at project close.
