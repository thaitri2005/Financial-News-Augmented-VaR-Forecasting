# Research log

A dated record of what was tried, what was seen, and what was decided. Newest entries last. Development results are from target dates up to 2023-12-13 unless stated; nothing after that date was evaluated before the preregistration listed below.

## 2026-11-24 — Study 1: sentiment in a quantile regression

- Built the pipeline: GDELT title extraction, FinBERT scoring of a 27% title sample, 19 daily features, penalized linear quantile regression, baselines.
- Preregistered and evaluated once on 500 forecasts (2023-12-14 to 2025-12-31).
- **Result:** sentiment changed the 5% quantile loss by −0.06%; the interval includes zero. See [results.md](results.md).

## 2026-11-24 — Diagnosis

Run on training and development rows only ([`scripts/diagnose_news_signal.py`](../scripts/diagnose_news_signal.py)).

- Negative tone correlates 0.59 with VIX; mostly redundant with market state.
- The share of negative headlines still predicts next-day log absolute return after controls (t = 2.9).
- "Quantile = constant × VIX" matches the 9-feature regression: the model had too many parameters for 700 rows.
- **Decision:** move to a volatility-first design ([next-methodology.md](next-methodology.md)).

## 2026-11-24 — Study 2 set-up

- **New data.** Daily open-high-low-close bars for the S&P 500 (Yahoo), validated against FRED closes: 2,511 common sessions, two differ by more than 1 bp, largest gap 12 bp. Used for range-based variance and the open-to-close return.
- **Fresh period.** GDELT titles extracted for 2026-01-01 to 2026-11-23 (327 days, all batches verified). No model or loss had ever been computed on 2026.
- **Two forecast contracts.**
  - *Pre-close:* forecast for session `s` made 30 minutes before the close of `s-1`; market inputs through `s-2`.
  - *At-open:* forecast for session `s` made at its open; market inputs through the close of `s-1` plus the overnight gap; news from the previous close to 15 minutes before the open.
- **Baseline.** Log-linear HAR on range-based variance plus VIX, refitted monthly on an expanding window; VaR and ES by filtered historical simulation.

### First development run (out-of-sample inside 2021–2023)

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
| Preregistration and evaluation enforced less than documented | All protocol constants are frozen in the record and compared at evaluation, with the commit, lockfile and date ordering; evaluation refuses to overwrite |
| Slices of the holdout were refitted separately | Forecasts are produced once and sliced |
| A month was skipped if its first day had too few training rows | Refits are retried until they succeed |
| Calibration compared models on different days | All models are summarized on common sessions |
| In-sample standardized returns made VaR too tight | The tail now uses past out-of-sample standardized returns once 250 are known |
| Unscored headlines were dropped silently | Windows need 20 scored headlines and 98% coverage of the designated sample |

After the fixes the HAR VaR is calibrated on development data: 34 breaches against 31.4 expected (pre-close), 40 against 31.5 (at-open).

### Supervised text model

Idea from Manela and Moreira's news-implied volatility: let the data choose which words matter.

- Vocabulary: 5,000 most frequent one- and two-word terms in titles first seen by 2020-12-31 (at least 200 titles each). Fixed thereafter.
- Feature: share of a window's retained headlines containing each term. Uses every retained headline, so no sampling and no FinBERT.
- Model: ridge regression of the HAR residual on the term shares. Penalty chosen by 5-fold blocked cross-validation inside the training rows at every refit. The out-of-fold prediction sets a stacking weight, floored at zero, so a text model without out-of-fold signal contributes nothing.

| Development, out-of-sample 2021–2023 | Pre-close | At-open |
|---|---:|---:|
| QLIKE gain over HAR | +3.75% (t = 1.83, one-sided p = 0.034) | +3.14% (t = 1.81, p = 0.035) |
| 5% pinball gain | +2.18% | +3.19% |
| 5% breaches (31.4 / 31.5 expected) | 32 | 37 |
| QLIKE gain by year: 2021, 2022, 2023 | +0.006, +0.008, +0.019 | −0.005, +0.010, +0.017 |

- The gain grows as the training sample grows, as expected for a learned model.
- **Penalty grid check.** Every refit chose the largest penalty in the grid {10, 100, 1,000, 10,000}. A grid shifted up by 100× gave +2.3% (pre-close) and +3.3% (at-open). The original grid is kept; the pre-close gain is sensitive to this choice and that is noted as a weakness.

Everything tried on development data is listed in this log. The number of variants is small, but it is not one, so development figures are optimistic.
