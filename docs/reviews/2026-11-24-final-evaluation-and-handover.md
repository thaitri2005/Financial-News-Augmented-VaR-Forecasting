# 2026-11-24 — Preregistration, locked evaluation, conclusion and handover (M4, M5, M6)

**Scope:** M4-02–M4-05, M5-01–M5-04, M6 scope decision, and a cross-document review of README, plan, status and blueprint. **Reviewer role:** implementing agent (self-review, not independent).

**Conclusion: no reliable improvement.** On the locked test, adding FinBERT sentiment aggregates of GDELT titles to a quantile model that already had market features and news counts did not improve the 5% next-session VaR forecast. The result is a qualified, reduced-power historical-proxy result (see the [admission review](2026-11-24-news-admission-and-development-gate.md)).

Records: [preregistration](../research/preregistration_20261124.json), [development record](../research/development_record_20261124.json), [final evaluation](../research/final_evaluation_20261124.json), [generated tables and figures](../research/final_result_tables.md).

## Order of events (the gate that matters)

| Step | Evidence |
|---|---|
| Admission and split fixed from eligibility counts, no return read | commit `c41c720`, admission record |
| Development search on target dates 2022-12-13 – 2023-12-13 only | development record |
| Preregistration `9a49621a…cd53` written from a clean tree at commit `c41c720`, then committed and pushed | commit `eff6193` |
| Locked test opened once; the command refuses to overwrite an existing final record | final evaluation record |
| Reporting code changed afterwards (figure line breaks at feed gaps only) | `src/newsvar/report.py`; no forecast or score is recomputed by the report |

No feature, setting, split or method was changed after the test was opened.

## Development (250 forecasts, selection only)

- 18 linear runs and 24 tree runs, all 250 forecasts ready in each; 2 origins ineligible.
- Selected L1 penalty: 0.01 for Q0/Q1/Q2 at 5%; 0.001 at 1%. Selected tree: depth 1, 200 trees at 5%; depth 2, 200 trees at 1%.
- Strongest baseline: GARCH-t at 5%, Gaussian EWMA at 1%.
- 5% tail: Q2 vs Q1 +0.51% (interval includes zero); Q1 vs Q0 −4.71% (counts hurt); Q0 with VIX vs without +9.19%.
- The quantile models were over-conservative in development: 5 breaches against 12.5 expected (Kupiec p = 0.014). They were trained mostly on 2020–2022, a more volatile period than 2023.

## Locked test (target dates 2023-12-14 – 2025-12-31)

500 eligible forecasts; 13 origins had no forecast because of the June–July 2025 GDELT outage. Every monthly fit succeeded. Scores are mean pinball loss in basis points of return.

### Primary comparison — Q2 (market + counts + sentiment) vs Q1 (market + counts), 5% tail

| Measure | Value |
|---|---|
| Common forecasts | 500 |
| Q1 mean pinball | 11.315 bp |
| Q2 mean pinball | 11.322 bp |
| Mean improvement | −0.0066 bp |
| Relative gain | −0.06% |
| 95% interval, block 20 | [−0.0222, +0.0058] bp |
| 95% interval, block 10 / block 5 | [−0.0203, +0.0054] / [−0.0178, +0.0039] bp |
| Preregistered claim supported | **no** |
| 2% practical-interest threshold met | no |

By target year: 2023 0.0000 bp (11 pairs), 2024 0.0000 bp (252 pairs), 2025 −0.0140 bp (237 pairs). The two models' forecasts are almost identical: at the selected penalty the regression gives the sentiment features almost no weight.

### 5% tail, all models

| Model | Breaches (25 expected) | Mean pinball (bp) | Kupiec p |
|---|---:|---:|---:|
| Q0 market | 23 | 11.340 | 0.678 |
| Q1 + news counts | 23 | 11.315 | 0.678 |
| Q2 + sentiment | 23 | 11.322 | 0.678 |
| T0 / T1 / T2 trees | 28 / 29 / 29 | 11.672 / 11.513 / 11.251 | 0.546 / 0.423 / 0.423 |
| B2 GARCH-t (development-selected strongest baseline) | 26 | 11.890 | 0.838 |
| B3 filtered historical simulation | 26 | 11.910 | 0.838 |
| B1 Gaussian EWMA | 30 | 12.173 | 0.319 |
| B0 historical simulation (250) | 30 | 12.179 | 0.319 |

Secondary, exploratory comparisons at 5%:

| Comparison | Relative gain | 95% interval (bp) |
|---|---:|---|
| Q1 vs Q0 (news counts) | +0.22% | [+0.0013, +0.0464] |
| Q2 vs Q0 (counts + sentiment) | +0.16% | [−0.0079, +0.0410] |
| Q0 vs GARCH-t | +4.62% | [−0.1405, +1.4459] |
| Q2 vs GARCH-t | +4.78% | [−0.1280, +1.4737] |
| Q0 with VIX vs without | +2.88% | [−0.0757, +0.7760] |
| T2 vs T1 (trees, sentiment) | +2.27% | [−0.3599, +1.1710] |

- The news-count gain of 0.22% is statistically distinguishable from zero here but economically negligible, and it had the opposite sign in development. It is not a claim.
- The market-only quantile regression beat GARCH-t by 4.6%, but the interval includes zero.
- Calibration is acceptable for every model at 5%; no independence test rejects.

### 1% tail (exploratory: 5 expected breaches)

- Q0, Q1 and Q2 each had 9 breaches (1.8%); Kupiec p = 0.106.
- Q2 vs Q1: +3.77%, interval [−0.2096, +0.6530] bp. Not distinguishable from zero.
- Q2's 1% quantile crossed above its 5% quantile on 10 of 500 days; Q0 and Q1 never crossed. Raw quantiles are reported unsorted.

### Sensitivities (5% tail, features rebuilt and models refitted)

Q2 vs Q1 relative gain: availability buffer 60 minutes +0.02%; 240 minutes −0.01%; news delayed one session 0.00%; sentiment lagged 5 origins 0.00%; lagged 20 origins −0.15%; recap headlines excluded +0.02%; dominant training source (`prnewswire.com`) excluded −0.03%; counts including duplicates −0.07%. Every interval includes zero. By ex-ante volatility regime: low −0.0025 bp (283 pairs), middle −0.0244 bp (154), high +0.0183 bp (63).

Nothing in the sensitivities changes the primary reading.

## Interpretation and limits

1. **What was tested.** Tone of a broad feed of web page titles that GDELT tagged with a stock-market theme and a US location, scored by a frozen 2020 FinBERT, aggregated per pre-close news window. This is not a curated vendor headline feed. About one audited title in seven was off-topic.
2. **Power is low.** 500 test forecasts give 25 expected breaches at 5%. A small true effect would not be detectable. The result does not show that news sentiment can never help; it shows that this feed and these features did not help here.
3. **Sentiment was sampled.** A 27% content-hash sample (about 740 scored titles in a median test window) adds noise to the aggregates. That can weaken a real signal but not manufacture one.
4. **Timing is a proxy.** Availability is GDELT batch time plus 15 minutes (Class B). The forecasts are a historical replay, not issued predictions.
5. **Source continuity.** 2020 fell below the 90% per-year completeness rule and the reduced-study split was applied. Under the strict contiguous-interval reading the sample would be prototype grade.
6. **One development fold.** Selection rested on 250 forecasts from one calm year; development and test disagreed on the sign of the news-count effect.
7. **Regularization.** With L1 penalty 0.01 the linear model largely ignores the news features. A lower penalty was tried in development and was worse.

Blueprint outcome class (§1): **negative research result, qualified by chronology and reduced power**. Not a shadow-use candidate: the §17.4 promotion rule requires a supported primary claim.

## M6 scope decision

Research-only delivery, as the plan allows by explicit decision:

| Task | State | Reason |
|---|---|---|
| M6-01 manual daily run | deferred | The primary claim is unsupported, so no news model is promoted to prospective use. The reproducible manual pipeline is the staged study commands. |
| M6-02 recovery and monitoring | partly met | Every stage is resumable with atomic commits and checksums. Continuous RSS monitoring and a single-writer lock are not implemented. |
| M6-03 scheduling and shadow log | cancelled for v1 | No promoted model; the cloud container is not a scheduling host. |
| M6-04 handover | done | README lists the working commands in order; status and this review record evidence and limits. |

## Resources actually used (4 CPUs, 15 GiB RAM, Linux container)

| Stage | Wall time | Notes |
|---|---|---|
| GDELT extraction | about 2 h 50 min | 1.128 TiB streamed, 1.1 GiB kept |
| Corpus build | 3 min 9 s | single process |
| FinBERT scoring | about 3 h 50 min | 967,729 titles, 62–117 titles/s |
| Admission audit | 14 s | |
| Development search | 4 min 40 s | 42 walk-forward runs, baselines, 8 sensitivities |
| Final evaluation | 3 min 13 s | |

Peak process memory was not instrumented; the machine never dropped below about 9 GiB available during these stages.

## Checks

- 106 tests pass; Ruff lint/format and strict mypy pass on 28 source files.
- All private artifacts are checksum-addressed; committed evidence contains counts, hashes and aggregate scores only. No title text, price series or per-date forecast is in Git. The two figures show test-period forecasts and realized returns as images.

## Cross-document review

| Document | Finding | Action |
|---|---|---|
| README | Described a Windows-only, pre-news state; commands used a Windows bootstrap path | Rewritten: current state, Linux commands, study pipeline, results |
| Blueprint | Status line, §5.4/§5.9 route, §6 admission, §16.1 split and §24 were pre-admission | Updated to version 2.6 with the streaming route, admission outcome, reduced split and result; original rules kept as history |
| Development plan | Next-ready queue predated source admission | Revision 2.0 records the completed stages and the M6 scope decision |
| Status | Said "no commits"; listed M3/M4 as waiting | Rewritten with final task states and next actions |
| Tests | One date-dependent calendar test had started failing | Fixed |

## What would make a stronger follow-up

1. A curated, timestamped headline feed (for example a free Alpaca/Benzinga entitlement pilot, blueprint §5.2) with the full 2017–2025 split.
2. Scoring every retained title instead of a 27% sample, which needs about 14 hours on this hardware.
3. A human-rated domain audit and a publisher allowlist frozen on training data.
4. Prospective logging from now on, which upgrades availability from Class B to Class A.

Any of these is a new study with its own preregistration; the 2023-12-14 – 2025-12-31 period is now spent as a confirmatory test for this design.
