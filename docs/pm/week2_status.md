# SENTINEL — Week 2 Status Report

**Period:** Sep 14–20, 2026  
**Prepared by:** Yash Narotam  
**Distribution:** Portfolio / GitHub  
**Schedule status:** ✅ ON TRACK — all milestones delivered on or ahead of target

---

## Summary

Week 2 delivered the full analytics layer (Phases 3–4) and the PM documentation suite (Phase 5), closing the project on the Sep 20 target. Phase 3 ran 2 days ahead of plan, creating buffer that absorbed the Grafana 10 JSON debugging on Phase 4. The final test count stands at 67/67 across all three test modules. The `scripts/final_check.py` verification script confirms the complete system is operational.

**Key numbers this week: 590 → 393 sensors selected; ~110 anomalies flagged (7%); 6 Grafana panels live; 67/67 tests green; 8 risk items closed.**

---

## Completed This Week

| Item | Output | Phase |
|------|--------|-------|
| Feature selection pipeline | 4-step filter (missing → constant → corr → MI); 590→393 sensors; `selected_features.csv` + `secom_features` table | P3A |
| SPC I-MR control charts | `spc.py` — σ̂ = MR̄/d₂; 4 Western Electric rules; ~400 flags written to `spc_flags` | P3B |
| Anomaly detection | `anomaly.py` — IsolationForest, contamination=0.07; `secom_raw.anomaly_score` + `.is_anomaly`; `anomaly_summary.csv` | P3C |
| Yield correlation | `yield_analysis.py` — RandomForest 200 trees, class_weight='balanced'; `yield_feature_importance.csv`; `yield_drivers` table | P3D |
| Analytics migration | `004_spc.sql` — `spc_flags`, `yield_drivers`, anomaly columns on `secom_raw` (idempotent) | P3 |
| Analytics test suite | 23 pure unit tests — all 4 WE rules, feature selection steps, IsoForest shape, RF importances | P3 |
| Grafana datasource | `postgres.yml` verified; `sentinel_postgres:5432` routing confirmed within Docker network | P4 |
| Grafana provisioner | `sentinel.yml` — scoped to `SENTINEL` folder; 30s auto-reload; `dashboard.yml` deactivated to prevent duplicate load | P4 |
| 6-panel dashboard | `sentinel_overview.json` — yield trend, quality stat, anomaly summary, sensor health barchart, anomalous readings table, SPC events table | P4 |
| Ops reader guide | `DASHBOARD.md` — plain-English panel guide, WE rule reference, navigation instructions | P4 |
| `dashboard-check` | Makefile target — Grafana health API + panel count verification + browser open | P4 |
| PM documentation | WBS, milestones + Gantt, risk register (8 risks), week 1/2 status reports, requirements | P5 |
| README rewrite | Full architecture document with Mermaid diagram, setup guide, Makefile reference | P5 |
| Final check script | `scripts/final_check.py` — 15-point system verification with READY/NOT READY output | P5 |

---

## In Progress

Nothing in progress — project is complete.

---

## Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| **Grafana 10 `barchart` `xField` property** — the horizontal barchart did not auto-detect the categorical X axis when the SQL column was renamed from its original name. Panel rendered as a time-series line chart instead of bars. | Sensor health panel (Panel 3) displayed incorrectly for ~1 h. **+1.0 h.** | Set `options.xField: "Sensor"` explicitly in the JSON to match the SQL alias. Also set `"format": "table"` on the target (not `"time_series"`). |

---

## Risks Closed This Week

| Risk | Resolution |
|------|------------|
| R-001 (High missing values) | Feature selection step 1 validates and removes >40%-missing sensors |
| R-003 (Grafana connectivity) | `dashboard-check` target confirms connection before user opens browser |
| R-004 (Class imbalance) | `class_weight='balanced'` + per-class classification report; framing clear |
| R-006 (Timeline slippage) | Analytics ran 2 days early, absorbing Grafana debug time |
| R-008 (Scope creep) | Out-of-scope items documented in `requirements.md`; scope held |

---

## Metrics

| Metric | Value |
|--------|-------|
| Phases completed | 5 of 5 (100%) |
| Tests passing | 67 / 67 |
| DB tables | 10 (all populated) |
| Sensors selected | 393 / 590 |
| Anomalies flagged | ~110 (7.0% of 1,567 runs) |
| SPC flags written | ~400 (across top-10 sensors, 4 WE rules) |
| Grafana panels | 6 |
| PM documents | 6 (WBS, milestones, risks, 2× status, requirements) |
| Estimated hours this week | 27.0 h |
| Actual hours this week | 30.0 h |
| Schedule variance | +3.0 h (+11%) |

---

## Post-Mortem Notes (for future projects)

1. **Profile before you parse** — running the data profiler in Phase 1 revealed the timestamp anomaly within minutes. Pattern: always validate source file structure before building the ingest pipeline.
2. **Grafana docs lag the release** — Grafana 10 introduced breaking changes in barchart panel options; the official docs still showed the Grafana 9 schema. Pattern: read the schema version changelog, not just the feature docs.
3. **MI ranking was the right pivot** — removing the high-correlation step alone (step 3) only reduced ~14 sensors. The MI step (step 4) identified which of the remaining 393 sensors actually matter for yield prediction. Both steps are load-bearing.
4. **class_weight='balanced' is not enough for 14:1 imbalance** — recall on the fail class was still 24% even with balanced weights. For a production model, SMOTE oversampling would be the next step. Documented in requirements as out-of-scope.
