# SENTINEL — Milestone Schedule

**Project:** SENTINEL — Manufacturing Process Monitoring & Yield Analytics  
**Sprint:** 2 weeks (Sep 7–20, 2026)  
**Overall status:** ✅ ON TRACK — all milestones delivered on or ahead of target

---

## Milestone Table

| # | Milestone | Target | Actual | Status | Notes |
|---|-----------|--------|--------|--------|-------|
| M1 | Repo skeleton committed; Docker stack starts cleanly | Sep 8 | Sep 8 | ✅ DONE | — |
| M2 | 1,567 SECOM records ingested with full audit trail (`batch_id`, timestamps) | Sep 11 | Sep 11 | ✅ DONE | +1.5 h timestamp parse bug; resolved same day |
| M3 | Validation engine live; quality scores written to PostgreSQL; HTML report generated | Sep 15 | Sep 15 | ✅ DONE | — |
| M4 | Feature selection complete; 590 → 393 sensors; `secom_features` populated | Sep 17 | Sep 15 | ✅ DONE (−2 d) | Completed ahead of schedule |
| M5 | SPC flags, anomaly scores, yield model importances all written to DB | Sep 18 | Sep 17 | ✅ DONE (−1 d) | — |
| M6 | Grafana dashboard provisioned; all 6 panels return data on `docker compose up` | Sep 19 | Sep 19 | ✅ DONE | — |
| M7 | PM artifact suite committed; `README.md` production-ready; 67/67 tests green | Sep 20 | Sep 20 | ✅ DONE | — |

---

## Gantt Chart

```mermaid
gantt
    title SENTINEL — 2-Week Sprint
    dateFormat YYYY-MM-DD
    axisFormat %b %d

    section Phase 0
    Environment & skeleton         :done, p0,  2026-09-07, 1d

    section Phase 1
    SECOM profiling                :done, p1a, 2026-09-08, 1d
    Schema + audit migrations      :done, p1b, 2026-09-09, 1d
    Ingest pipeline + ERD          :done, p1c, 2026-09-10, 2d
    Phase 1 tests (17)             :done, p1d, 2026-09-11, 1d

    section Phase 2
    Validation rules engine        :done, p2a, 2026-09-12, 1d
    Quality scoring + DB write     :done, p2b, 2026-09-13, 1d
    HTML report + tests (27)       :done, p2c, 2026-09-15, 1d

    section Phase 3
    Feature selection (4-step)     :done, p3a, 2026-09-15, 1d
    SPC I-MR charts (4 WE rules)   :done, p3b, 2026-09-16, 1d
    Anomaly detection (IsoForest)  :done, p3c, 2026-09-17, 1d
    Yield correlation (RF)         :done, p3d, 2026-09-17, 1d
    Analytics tests (23)           :done, p3e, 2026-09-17, 1d

    section Phase 4
    Grafana provisioning           :done, p4a, 2026-09-18, 1d
    6-panel dashboard JSON         :done, p4b, 2026-09-19, 1d

    section Phase 5
    PM documentation suite         :done, p5a, 2026-09-19, 1d
    README + final polish          :done, p5b, 2026-09-20, 1d
```

---

## Phase Dependencies

```
P0 (skeleton) ──► P1 (ingest) ──► P2 (validate) ──► P3 (analytics) ──► P4 (dashboard)
                                                                              │
                                  P5 (PM) ◄─────────────────────────────────┘
```

P3 analytically depends on P2 (validated data in DB).  
P4 depends on P3 (analytics tables must be populated for SPC + anomaly panels).  
P5 runs in parallel with P4 final polish; requires all other phases complete.

---

## Definition of Done (per phase)

- **P0:** `make up` starts all containers; `make test` runs without error
- **P1:** `make ingest` completes; `SELECT COUNT(*) FROM secom_raw` = 1,567
- **P2:** `make validate` + `make quality-report` complete; HTML renders in browser
- **P3:** `make analytics` completes; `spc_flags`, `yield_drivers` tables populated; 67/67 tests
- **P4:** `make dashboard-check` shows 6 panels; Grafana auto-loads on `docker compose up`
- **P5:** `scripts/final_check.py` prints `SENTINEL READY`; all PM docs committed
