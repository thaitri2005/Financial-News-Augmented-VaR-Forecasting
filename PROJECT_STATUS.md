# Project status and agent handover

**Updated:** 2026-09-16 · **Current milestone:** M2 market-risk reference passed; M3 engineering may proceed without predictive use · **Study news source:** not admitted.

## Current outcome

The blueprint remains the scientific/architectural source of truth. The separate development plan and persistent agent workflow remain in place. The core, immutable raw-page store, XNYS calendars, retained market source-quality audit, and versioned market/label Parquet tables are implemented and checked. News ingestion, NLP, forecasting and runtime monitoring are not implemented.

**Active task:** M3-03, deterministic market/count/sentiment feature builders on synthetic inputs. M3-01 awaits the live sentiment resource gate. M0-04 awaits external free-sandbox access. M0-05, M1 and M2 have passed task reviews; predictive news use remains blocked.

## Task ledger

| ID | State | Evidence / next requirement |
|---|---|---|
| M0-01 | done | Separate plan, agent instructions, status and cross-document review |
| M0-02 | done | Python 3.12.14, uv 0.12.15 bootstrap, `pyproject.toml`, `uv.lock`, `.venv`, CLI help; core scope only |
| M0-03 | done | Resource doctor, 10 passing tests, Ruff/format/mypy checks, live preflight evidence |
| M0-04 | waiting access | [GDELT pilot contract](docs/development/m0_gdelt_pilot_contract.md) and capped [catalog evidence](docs/research/gdelt_catalog_pilot_20260916.json) prepared; a user-owned free BigQuery sandbox or free Alpaca credential is needed for source admission |
| M0-05 | done | [Benchmark contract](docs/development/m0_finbert_benchmark_contract.md), [10,000-title evidence](docs/research/finbert_benchmark_10000_20260916.json), [review](docs/reviews/2026-09-16-m0-finbert-benchmark.md); CPU FP32 path passed at 0.90 GiB peak RSS, but source admission remains open |
| M0-06 | planned | Overall M0 gate open; source/scope and NLP resource decisions not evaluated |
| M1-01 | done | [Storage contract](docs/development/m1_raw_commit_contract.md), [review](docs/reviews/2026-09-16-m1-data-foundation.md), 8 restart/integrity fixtures, Ruff/mypy |
| M1-02 | done | [Calendar contract](docs/development/m1_calendar_contract.md), [review](docs/reviews/2026-09-16-m1-data-foundation.md), 7 fixtures, saved/reloaded 2,337-origin artifact |
| M1-03 | done | [Market contract](docs/development/m1_market_contract.md), [coverage report](docs/research/market_coverage_20260916.json), [cross-review](docs/reviews/2026-09-16-m1-market-cross-review.md); 2,337 matched closes, 27 VIX closure rows excluded, 12 market fixtures, full checks |
| M1-04 | done | [Label contract](docs/development/m1_label_contract.md), [quality report](docs/research/label_quality_20260916.json), [review](docs/reviews/2026-09-16-m1-labels.md); 6 temporal fixtures, 2,335 labels with proxy availability, 2 explicit right-edge exclusions, full checks |
| M1-04B | done | [Persistence contract](docs/development/m1_market_persistence_contract.md), [dataset evidence](docs/research/market_dataset_20260916.json), [review](docs/reviews/2026-09-16-m1-market-persistence.md); extended calendar, 4,792 observations, 2,336 labels, two boundary exclusions and integrity/replay fixtures |
| M2-01 | done | [Baseline contract](docs/development/m2_baseline_contract.md), [review](docs/reviews/2026-09-16-m2-baselines.md), 8 numerical/causal fixtures; historical simulation and Gaussian EWMA only |
| M2-02 | done | [Ledger evidence](docs/research/m2_development_ledger_20260916.json), [review](docs/reviews/2026-09-16-m2-walkforward.md); 1,006 private 2021-2022 attempts, checksum manifest, no final-period results |
| M2-03 | done | [Causal GARCH/FHS ledger evidence](docs/research/m2_garch_development_ledger_20260916.json), 1,006 checksum-validated private attempts (503/model), 50,000 paths, 0.999 persistence cap and protected metric-input join |
| M2-04 | done | [Metric contract](docs/development/m2_metrics_contract.md), [review](docs/reviews/2026-09-16-m2-metrics.md); strict pinball/breach, exact interval, common-date and missing-session fixtures |
| M2-05 | done | [Reference gate](docs/research/m2_reference_gate_20260916.json), [review](docs/reviews/2026-09-16-m2-reference-report.md); M2 market-only foundation passed without publishing scores or opening final-period evaluation |
| M3-01 | waiting resources | [Encoder/cache contract](docs/development/m3_encoder_cache_contract.md), synthetic cache/identity fixtures and local fingerprint check passed; live inference smoke test waits for the 5 GiB sentiment resource gate (4,403,625,984 bytes available at 2026-09-16T06:00:11Z) |
| M3-03 | waiting access | [Feature contract](docs/development/m3_features_contract.md), [review](docs/reviews/2026-09-16-m3-features-review.md), 3 synthetic causal fixtures passed; full materialization needs source admission |
| M4-01 | done | [Linear quantile contract](docs/development/m4_linear_quantile_contract.md), [review](docs/reviews/2026-09-16-m4-linear-quantile-review.md), 3 synthetic preprocessing/unit/persistence fixtures passed; no data-backed fit |
| M4-02 | done | [Search-plan contract](docs/development/m4_search_plan_contract.md), 36-run preferred and 18-run GDELT alternative manifests validated with synthetic fixtures; no model run |
| M3-02/M3-04/M4-03+ | waiting access | Source-backed audit/materialization, experiments and preregistration require an admitted predictive news dataset; source access remains absent |

Later tasks remain `planned` in the development plan until promoted here. A completed core sub-gate does not imply passed news-source or NLP gates.

## Current task brief: gate watch and source-independent maintenance

**Title:** Resolve the next ready external gate while preserving the completed market-only branch. **Owner:** implementing agent.

- Outcome: run M3-01's local smoke test if live RAM reaches 5 GiB; otherwise await free-source admission for M1/M3/M4 data-dependent work.
- Scope: no unqualified text, source substitution, experimental run or final-period access.

**Following task:** M3-01 live loader smoke test after the resource gate; M1-05 remains waiting for source access.

## Dependencies and live-resource evidence

- No news source is admitted. Yahoo/FNSPID/GDELT samples are feasibility evidence, not complete historical feed validation.
- Alpaca credentials remain unavailable; the user offered a free account if necessary. Prepare the capped pilot before requesting only the relevant local credential location/names. No paid service is authorized.
- Latest doctor at 2026-09-15T20:56:36.791459Z: 7,084,969,984 bytes available RAM (~6.60 GiB), 75,662,659,584 bytes disk free (~70.47 GiB). Diagnostics, normalization and sentiment gates passed. Recheck live resources before heavy work.
- The optional ML group and bounded inference benchmark now exist. Model fit, feature tables, backtests, live memory monitoring and CI workflow do not.
- Git repository still has no commits. No commit/publication was requested or performed; source payloads and environments remain ignored.

## Reviews and evidence

- Last cross-document review: [2026-09-16 M3/M4 source-gate review](docs/reviews/2026-09-16-m3-m4-cross-review.md). M2 passed as a market-only development foundation; the predictive news gate remains open.
- Latest verification: 83 tests passed with the locked offline risk/ML/modeling environment; Ruff lint/format and strict mypy passed. The full suite reports four existing third-party calendar deprecation warnings; no project test failed. The M2 reference report has no published private score/final-period result.
- Previous research evidence remains in `docs/research/`, notebook 00 and blueprint §24; its dated verification report is historical, not a check of newly added implementation files.

## Resume commands

```powershell
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar doctor --json
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline pytest -q
```

Read `AGENTS.md`, the active M3-01 task and applicable blueprint sections; inspect actual files/Git state. Preserve all delivered raw snapshots. Update this record with evidence and the next action at handover.
