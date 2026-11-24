# Project status and agent handover

**Updated:** 2026-11-24 · **Current milestone:** M5 passed (research release); M6 closed as research-only by explicit scope decision · **Study news source:** GDELT titles, admitted for a qualified, reduced-power historical-proxy study.

## Current outcome

The first release is complete as a research deliverable. The locked test was opened once under preregistration `9a49621a…cd53`.

**Result: no reliable improvement.** Q2 (market + news counts + sentiment) versus Q1 (market + news counts) at the 5% tail on 500 common forecasts: relative gain −0.06%, 95% block-bootstrap interval [−0.0222, +0.0058] bp. The preregistered claim is not supported. See the [final review](docs/reviews/2026-11-24-final-evaluation-and-handover.md).

**Active task:** none. **Next action:** see "Next executable actions" below; none is required to keep the delivered result valid.

## Task ledger

| ID | State | Evidence / note |
|---|---|---|
| M0-01 – M0-03 | done | Unchanged from 2026-09-16; [foundation review](docs/reviews/2026-09-15-foundation.md) |
| M0-04 | done | Streaming GDELT route (CHG-001); [ingestion gate](docs/reviews/2026-11-24-gdelt-stream-ingestion-gate.md), [extraction ledger](docs/research/gdelt_extraction_20261124.json). The BigQuery and Alpaca pilots were never run |
| M0-05 | done | September benchmark; pinned files re-verified by hash on 2026-11-24 |
| M0-06 | done | Reduced news study branch; [admission review](docs/reviews/2026-11-24-news-admission-and-development-gate.md) |
| M1-01 – M1-04B | done | Rebuilt here from a fresh snapshot: calendar `6494526f…15a4`, market dataset `66a1ae68…d98b`, 2,286 labels; [snapshot manifest](docs/research/market_snapshot_20261124.json) |
| M1-05 | done | `ingestion/gdelt.py`; 216,999 batches verified, 5,054 absent, 91 HTTP 404 |
| M1-06 | done with limitation | Class B batch-time availability; no publisher timestamp exists to audit. 200-headline audit is agent-rated |
| M1-07 | done | `news.py`; corpus `d2287582…ebbe5`, 3,794,159 retained events, 3,582,698 unique titles; [manifest](docs/research/news_corpus_20261124.json) |
| M1-08 | done | [Admission record](docs/research/news_admission_20261124.json): 1,441 usable rows; 2020 fails the 90% per-year continuity rule (84.2%) |
| M2-01 – M2-05 | done | Code unchanged; baselines rerun inside the study on the new dataset. The September private ledgers were not carried over |
| M3-01 | done | Live inference on the pinned snapshot; fingerprint `ca5cf73e…14e9` |
| M3-02 | done with limitation | Truncation 0.007%; audit 14–16% off-topic, 82% in-domain agreement; **single agent rater, no human** |
| M3-03, M3-04 | done | `feature_table.py`; frozen 27% scoring sample (CHG-003), 967,729 titles scored, 100% coverage of the designated sample |
| M4-01 | done | Unchanged |
| M4-02 | done | 18 linear runs under the reduced-study split (CHG-002); [development record](docs/research/development_record_20261124.json) |
| M4-03 | done | Eight rebuild-and-refit sensitivities, VIX ablation, strongest-baseline comparison |
| M4-04 | done | 24 tree runs; secondary only |
| M4-05 | done | [Preregistration](docs/research/preregistration_20261124.json), committed and pushed (`eff6193`) before evaluation |
| M5-01 – M5-04 | done | [Final evaluation](docs/research/final_evaluation_20261124.json), [tables and figures](docs/research/final_result_tables.md), [final review](docs/reviews/2026-11-24-final-evaluation-and-handover.md) |
| M6-01 | deferred | No model promoted; manual reproducible run is the staged study commands |
| M6-02 | partly done | Resumable, checksum-verified stages; no continuous RSS monitor or single-writer lock |
| M6-03 | cancelled for v1 | No promoted model and no scheduling host |
| M6-04 | done | README commands verified on 2026-11-24 |

## Deviations recorded

- **CHG-001:** streaming filter-and-discard extraction replaces the BigQuery pilot; raw GDELT payloads are not retained.
- **CHG-002:** reduced-study split (691 / 250 / 500) with a documented 2020 continuity exception. The study is not the planned full confirmatory study.
- **CHG-003:** sentiment scored on a frozen 27% content-hash sample; counts use the full feed.

## Environment and artifacts

- Work on 2026-11-24 ran in a cloud Linux container (4 CPUs, 15 GiB RAM). `data/`, `artifacts/` and `.cache/` are Git-ignored and **exist only in that container**. They are lost when it is reclaimed and must be rebuilt with the README commands (about 7 hours of processing).
- Rebuilt identifiers will differ from the recorded ones: FRED serves a rolling ten-year window and the GDELT catalog grows.
- The September laptop snapshots and M2 ledgers remain wherever the original laptop keeps them; nothing here depends on them.
- `.python-version` was relaxed from `3.12.14` to `3.12` and uv default groups were set so that plain `uv run --locked …` works.

## Open issues

1. The domain audit has no human rater.
2. No automated integration test covers the full study pipeline; a synthetic rehearsal was run by script.
3. Peak process memory was not instrumented during extraction or scoring.
4. Blueprint items never built: notebooks 01–08, DuckDB catalog, INT8 backend, runtime monitor, daily runbook automation.
5. The test period 2023-12-14 – 2025-12-31 is spent for this design. Any redesign needs a later period or prospective data.

## Next executable actions (optional follow-ups, each a new study)

1. Run the free Alpaca/Benzinga entitlement pilot (blueprint §5.2) if the user provides a free account key; a curated feed with 2017–2025 history would allow the preferred split.
2. Score all 3.58 million titles (about 14 hours) and rerun development only, to measure how much the 27% sample cost.
3. Start prospective logging of GDELT batches and forecasts to obtain Class A availability.

## Reviews and evidence

- Last cross-document review: [2026-11-24 final evaluation and handover](docs/reviews/2026-11-24-final-evaluation-and-handover.md).
- Completed implementation tasks since that review: 0.
- Latest verification: 106 tests passed; Ruff lint/format and strict mypy clean (28 source files).
