# Research log

A dated record of what was tried, what was seen, and what was decided. Newest entries last. Development results are from target dates up to 2023-12-13 unless stated. For study 2, no model was evaluated after that date before its preregistration; study 1 had been evaluated on 2023-12-14 to 2025-12-31.

## 2026-11-24 — Study 1: sentiment in a quantile regression

- Built the pipeline: GDELT title extraction, FinBERT scoring of a 27% title sample, 19 daily features, penalized linear quantile regression, baselines.
- Preregistered and evaluated once on 500 forecasts (2023-12-14 to 2025-12-31).
- **Result:** sentiment changed the 5% quantile loss by −0.06%; the interval includes zero. See [results-study1.md](results-study1.md).

## 2026-11-24 — Diagnosis

Run on training and development rows only ([`scripts/diagnose_news_signal.py`](../scripts/diagnose_news_signal.py)).

- Negative tone correlates 0.59 with VIX; mostly redundant with market state.
- The share of negative headlines still predicts next-day log absolute return after controls (t = 2.9).
- "Quantile = constant × VIX" matches the 9-feature regression: the model had too many parameters for 700 rows.
- **Decision:** move to a volatility-first design (now described in [methodology.md](methodology.md)).

## 2026-11-24 — Study 2 set-up

- **New data.** Daily open-high-low-close bars for the S&P 500 (Yahoo), validated against FRED closes: 2,511 common sessions, two differ by more than 1 bp, largest gap 12 bp. Used for range-based variance and the open-to-close return.
- **Fresh period.** GDELT titles extracted for 2026-01-01 to 2026-11-23 (327 days, all batches verified). No model or loss had ever been computed on 2026.
- **Two forecast contracts.**
  - *Pre-close:* forecast for session `s` made 30 minutes before the close of `s-1`; market inputs through `s-2`.
  - *At-open:* forecast for session `s` made at its open; market inputs through the close of `s-1` plus the overnight gap; news from the previous close to 15 minutes before the open.
- **Baseline.** Log-linear HAR on range-based variance plus VIX, refitted monthly on an expanding window; VaR and ES by filtered historical simulation.

### First development run (out-of-sample inside 2021–2023, before the review fixes)

| News term added to HAR | Pre-close QLIKE gain | At-open QLIKE gain |
|---|---:|---:|
| FinBERT negative-share surprise | +1.8% (t = 1.1) | +0.7% (t = 1.1) |
| FinBERT mean-negative surprise | +1.6% | +0.8% |
| FinBERT negative-share level | +2.1% | +0.8% |
| News-count surprise | +0.3% | +1.1% |

- Small, same sign every year, not significant. No VaR improvement.
- The HAR VaR under-covered: 44 breaches against 31 expected.

### Independent code review 1 (reviewer agent, read-only)

No look-ahead found; perturbation tests on synthetic data confirmed the information boundaries for both contracts. Problems found and fixed:

| Finding | Fix |
|---|---|
| Relative gain had the wrong sign for FZ0, whose mean is negative | Ratios are reported only for positive loss scales |
| Conditional predictive ability test ignored the two-step horizon of the pre-close contract | The test now includes `horizon − 1` autocovariances |
| Preregistration and evaluation enforced less than documented | See review 2 below |
| Slices of the holdout were refitted separately | Forecasts are produced once and sliced |
| A month was skipped if its first day had too few training rows | Refits are retried until they succeed |
| Calibration compared models on different days | All models are summarized on common sessions |
| In-sample standardized returns made VaR too tight | The tail now uses past out-of-sample standardized returns once 250 are known |
| Unscored headlines were dropped silently | Windows need 20 scored headlines and 98% coverage of the designated sample |

After the fixes, coverage tests no longer reject the HAR VaR on development data: 34 breaches against 31.4 expected (pre-close), 40 against 31.5 (at-open, Kupiec p = 0.14).

### Supervised text model

Idea from Manela and Moreira's news-implied volatility: let the data choose which words matter.

- Vocabulary: the 5,000 most frequent one- and two-word terms in titles first seen by 2020-12-31 (at least 200 titles each). Fixed thereafter.
- Feature: share of a window's retained headlines containing each term, transformed by `log1p(1000 × share)`. Uses every retained headline, so no sampling and no FinBERT.
- Model: ridge regression of the HAR residual on those features, with a stacking weight set from out-of-fold predictions (5 contiguous folds inside the training rows).
- In practice the cross-validation always picks the largest penalty in the grid {10, 100, 1,000, 10,000}, so the penalty is effectively fixed at 10,000 and the stacking weight does the tuning.

First run (index prices for both contracts): QLIKE gain +3.75% pre-close (t = 1.83) and +3.14% at-open (t = 1.81).

Variants tried on development data, all logged here:

| Variant | Pre-close QLIKE gain | At-open QLIKE gain | Kept? |
|---|---:|---:|---|
| Term-share levels, penalty grid 10–10,000 | +3.75% | +3.14% | yes |
| Same, grid shifted to 1,000–1,000,000 (scratch run, no record file) | +2.33% | +3.28% | no; shows the pre-close gain is sensitive to the grid |
| Abnormal usage against the previous 63 windows | +0.83% | +0.17% | no |
| Abnormal usage against the previous 21 windows | +0.69% | +0.14% | no |

### Independent review 2 (reviewer agent, read-only) — before preregistration

No look-ahead in the text path: vocabulary, folds, stacking, tail history and refits were perturbation-tested on synthetic data. Under pure-noise text the pooled test rejected in 0.8% of runs, so it is conservative. Findings and actions:

| Finding | Action |
|---|---|
| The index value at 09:30 is partly stale, so the at-open "gap" understated the overnight move and the catch-up sat inside the target | Measured on 2019-10-01 to 2023-12-13: the index gap has 51% of the variance of SPY's gap, and the index open-to-close return is 0.35 correlated with SPY's gap (SPY gap without dividend adjustment; a reviewer obtained 0.20 on 2021–2023). **The at-open contract now uses SPY bars** for the gap, the variance history and the target |
| In the pre-close contract the baseline sees prices only through `s−2` while headlines run to the cutoff on `s−1` | Disclosed in the preregistration. Oracle diagnostic below |
| The commit check would have refused evaluation once the registration was committed | Source is now identified by content: the Git tree of `src` and hashes of `pyproject.toml` and `uv.lock` |
| Several constants were not pinned (penalty grid, folds, stacking cap, tokenizer, transform, HAR windows, bootstrap settings) and the score table could change unnoticed | All are in the registration and compared at evaluation; the score parts are hashed; eligible holdout row counts are recorded |
| "Evaluate once" was only a file check | Output paths derive from the registration identifier; an "opened" marker is written before any outcome is computed; the registration must be committed |
| Forking paths only partly disclosed | The registration lists every development choice and states that the design was prompted by study 1's null result |
| The stacking weight let noise through | It is now zero unless the stacked out-of-fold prediction beats predicting zero. On noise some weight still passes, which can only hurt the challenger |
| Penalty and stacking per refit were not recorded | Recorded in the forecast ledger and summarized in the development record |
| Weak tail-leak test; no tests for the text path, pooled test or registration checks | Added |
| Log overstated a few points | Corrected in this file |

### Development results after review 2 (the frozen design)

Out-of-sample inside 2021-01-04 to 2023-12-13; the text model against the HAR baseline.

| Measure | Pre-close | At-open (SPY) | Pooled test |
|---|---:|---:|---|
| QLIKE gain | +3.75% (t = 1.83) | +4.27% (t = 1.85) | t = 2.08, one-sided p = 0.019 |
| 5% pinball gain | +2.18% (t = 1.59) | +3.39% (t = 2.28) | t = 2.21, p = 0.013 |
| 5% FZ0 improvement | +0.028 (t = 1.84) | +0.036 (t = 2.08) | t = 2.33, p = 0.010 |
| 5% breaches, text model | 32 of 31.4 expected | 34 of 31.5 expected | |
| 1% pinball gain | −1.24% | −0.13% | |
| QLIKE improvement by year, 2021 / 2022 / 2023 | +0.006 / +0.008 / +0.019 | −0.002 / +0.012 / +0.019 | |

Caveats on these numbers:

- The pooled QLIKE bootstrap interval at block length 20 includes zero (−0.0036 to +0.0254); the FZ0 and pinball intervals exclude it.
- The 1% tail is not improved.
- The yearly pattern is three points; 2021 has few forecasts. It is compatible with a model that improves with more training data and equally with a 2023 regime effect.
- The pre-close conditional test rejects equal conditional accuracy (p = 0.026): the gain depends on the state of the market.
- Stacking was zero for 3% (pre-close) and 7% (at-open) of forecasts; its mean was 0.65 and 0.58.
- FinBERT sentiment terms add 0.3–2.0% on QLIKE and nothing on VaR. The news-count surprise helps at the open (+1.6%, t = 2.7) but not before the close.
- The HAR baseline itself beats historical simulation by 7.5% (pre-close) and 11.7% (at-open) on 5% pinball loss.

### Oracle diagnostic for the pre-close contract (development only)

Question: is the text gain just headlines describing that day's market move? The baseline was given, unrealistically, the variance and VIX of session `s−1`.

| Baseline | Text QLIKE gain | 5% pinball gain |
|---|---:|---:|
| As declared (prices through `s−2`) | +3.75% (t = 1.83) | +2.18% |
| Plus same-day variance | +2.92% (t = 2.69) | +1.92% |
| Plus same-day variance and VIX | +3.37% (t = 3.34) | +0.56% |

The volatility gain survives; the VaR gain shrinks. News text carries volatility information beyond same-day daily market data on development dates, but most of its VaR value in the pre-close contract overlaps with what same-day VIX would give.

Everything tried on development data is listed in this log. The design was chosen there, so development figures are optimistic.

## 2026-11-24 — Study 2: preregistration and evaluation

- Rehearsed registration, verification and evaluation on development dates only (a pretend holdout of 2022-07-01 to 2023-12-13) to make sure nothing could fail after the real holdout was opened.
- Registration `3f5a032a…` committed and pushed before evaluation. Eligible holdout rows: 722 (pre-close) and 724 (at-open), 224 of them in 2026.
- Evaluated once. **Verdict under the registered rule: strong.**

| Test on the whole holdout | t | One-sided p |
|---|---:|---:|
| H1: pooled QLIKE | 2.75 | 0.003 |
| H2: pooled 5% FZ0 | 1.72 | 0.043 |
| Pooled 5% pinball | 2.55 | 0.005 |

- Per set-up: QLIKE +4.8% pre-close (Holm p = 0.010), +2.3% at-open (Holm p = 0.045).
- 2026 slice alone: pooled QLIKE t = 0.55 (not significant); pooled pinball t = 1.68. Pre-close QLIKE +4.3%, at-open −1.7%.
- FinBERT terms: intervals include zero in both set-ups. News-count surprise: +1.9% QLIKE in both (exploratory).
- Full tables: [results.md](results.md).

### Post-evaluation checks (descriptive, not registered)

- Excluding April 2025: pooled QLIKE t = 2.67.
- The best 1% of days supply 53% of the total QLIKE gain; trimming the best and worst 1% gives t = 4.27.
- The text model's stacking weight was never zero on the holdout; its mean was 0.60 (pre-close) and 0.56 (at-open).

## 2026-11-24 — Operations

- Added `newsvar update` and `newsvar forecast`. A day extracted before it ended is incomplete, so `update` re-extracts the last three days.
- The panel takes an `as_of` time: a session that has not closed has no outcome, even when a partial price bar exists.
- First live run: update in 5 minutes, forecast in 5.5 minutes. For the session of 2026-11-24 the text model gave a 95% VaR of −3.5% (pre-close) and −2.4% open-to-close (at-open). This is the first entry of the prospective log.

## 2026-11-24 — Final reviews (two AI reviewer agents, read-only)

### Claims and numbers

The referee recomputed the primary test from the forecast ledger (t = 2.749, identical to the record), confirmed that the registered outcome follows from the rule, that the registered source tree equals the tree at registration and at evaluation, and that the generated numbers match the records. It found no wrong arithmetic. It did find overstatement, corrected in the report, README, results and methodology:

| Finding | Correction |
|---|---|
| Robustness was reported for H1 only | Added: H2 fails the same checks (t = 1.37 without April 2025; two of three bootstrap intervals include zero); the at-open QLIKE gain depends on seven days |
| The 2026 slice was described too kindly | Now "inconclusive": pooled QLIKE t = 0.55 and driven by two days; registered FZ0 loss p = 0.19 |
| "Only term that clearly helps" contradicted the figure | Reworded: the news-count surprise has smaller gains with intervals excluding zero; the text model's at-open interval includes zero |
| "Calibrated" and "clearly beats historical simulation" | Replaced with the actual tests: 5% coverage not rejected; dynamic-quantile test rejects at 1% pre-close; the gain over historical simulation is not significant on the holdout alone |
| "Before any holdout outcome was evaluated" | Corrected: study 1 had been evaluated on the first 500 sessions |
| Caveats missing next to the headline | Added to the abstract, the answer, the README and the results summary |
| "Strong" could read as an effect size | Explained wherever it appears |
| The "live forecast" was produced after both forecast times | Described as a demonstration, with the VIX values each set-up actually used |
| The conditional test was read as state dependence | Corrected: the statistic includes the unconditional mean |
| No mention of multiple testing, or that all reviewers were AI agents | Added to the limits |

Not archived: the reviewers' reports, the audit ratings, the shifted-penalty-grid run and the reviewer's noise simulation. The oracle diagnostic is now in `scripts/oracle_diagnostic.py`.

The frozen registration's power note quotes a development pooled t of 2.05 from the run before SPY prices were adopted; the development record gives 2.08.
