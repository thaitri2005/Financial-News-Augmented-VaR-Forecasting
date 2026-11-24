# Methodology

This describes study 2, the volatility-first design that the forecasting system uses. Study 1, a sentiment quantile regression that found no effect, is in [methodology-study1.md](methodology-study1.md). The reasoning that led from one to the other is in the [research log](research-log.md).

## Question

Does news text improve next-day volatility, Value-at-Risk (VaR) and expected shortfall (ES) forecasts for the S&P 500, beyond a good model built from daily market data?

## Two forecast set-ups

| | Pre-close | At-open |
|---|---|---|
| Forecast made | 30 minutes before the close of session `s−1` | At the open of session `s` |
| Market inputs | Through the close of `s−2`, plus VIX | Through the close of `s−1`, plus VIX and the overnight gap |
| News window | From the previous cutoff to this cutoff | From the previous close to 15 minutes before the open |
| Target return | Index close of `s−1` to close of `s` | SPY open to close of `s` |
| Target variance | Squared overnight return + Garman–Klass range variance (index) | Garman–Klass range variance (SPY) |

The pre-close forecast cannot see the close of `s−1`, so it is effectively two steps ahead.

The at-open set-up uses SPY, the exchange-traded fund that tracks the index, because the index's own value at 09:30 is partly stale: many constituents have not traded yet. On development data the index's overnight gap had 51% of the variance of SPY's gap. A reviewer raised this before the test.

## Data

| Source | Use |
|---|---|
| FRED `SP500` | Index closes; close-to-close returns |
| Cboe VIX | Volatility control, prior close only |
| Yahoo daily bars, `^GSPC` and `SPY` | Open, high, low, close for range-based variance; SPY dividends to correct the gap on ex-dates |
| GDELT GKG 2.0, English | Page titles in 15-minute batches, each verified against the archive's checksum |

Index bars are validated against FRED closes; SPY returns must correlate at least 0.99 with index returns.

**News selection, deduplication, availability and completeness** are unchanged from study 1: web titles tagged `ECON_STOCKMARKET` with a US location; duplicates within 72 hours dropped in time order; a title is available 15 minutes after its batch; a window is used only if at least 95% of its batches were retrieved. Corpus: 4.33 million retained events from 2019-09-23 to 2026-11-23.

## Models

### Baseline: log-HAR with VIX

```text
log variance(s) = b0 + bd·log(last variance) + bw·log(5-day mean) + bm·log(22-day mean)
                + bv·log(VIX²) [+ bg·gap]
```

- Ordinary least squares, refitted on the first session of each month on all earlier sessions whose outcome was known.
- At least 250 training rows.
- The variance forecast applies the usual lognormal mean correction.

### Text model

1. **Vocabulary.** The 5,000 most frequent one- and two-word terms in titles first seen by 2020-12-31, each in at least 200 titles. English stop words removed. Never updated.
2. **Features.** For each news window, the share of retained headlines containing each term, transformed by `log1p(1000 × share)` and standardized on training rows. Every retained headline is used; there is no sampling and no language model.
3. **Ridge on the residual.** The baseline's log-variance residual is regressed on the features. The penalty is chosen from {10, 100, 1,000, 10,000} by 5-fold cross-validation over contiguous blocks of the training rows. In practice it always chooses 10,000.
4. **Stacking.** The prediction is multiplied by a weight: the slope of the residual on its out-of-fold prediction, limited to between 0 and 1.5, and set to zero unless the weighted out-of-fold prediction beats predicting zero.

Final forecast: baseline log variance plus the weighted text prediction.

### Other news terms (exploratory)

Each is one extra regressor in the HAR model:

- FinBERT share of negative headlines, as a level and as a surprise;
- FinBERT mean negative probability, as a surprise;
- news-count surprise.

A surprise is the residual from regressing the measure on VIX, the last known return and its own previous value, refitted monthly on past data. FinBERT terms use the 27% scored sample; a window needs at least 20 scored headlines.

### VaR and expected shortfall

Filtered historical simulation: divide each past return by its volatility forecast, take the 5% (or 1%) quantile and the mean below it, and multiply by the new volatility forecast. The standardized returns come from past out-of-sample forecasts once 250 are available; before that, from in-sample fitted volatilities.

### Reference model

250-day historical simulation on each set-up's own returns.

## Evaluation

| Element | Choice |
|---|---|
| Volatility loss | QLIKE |
| VaR loss | Pinball loss at 5% and 1% |
| Joint VaR and ES loss | FZ0 |
| Main test | One-sided Diebold–Mariano test with Newey–West errors |
| Pooling | The two set-ups' daily improvements are averaged per session and tested once |
| Supporting | Moving-block bootstrap (2,000 replications; blocks 20, 10, 5); Holm-adjusted per-set-up tests; Giacomini–White conditional test; Kupiec coverage and dynamic-quantile tests |

The baseline and the text model are nested and estimated on an expanding window, which makes the Diebold–Mariano test on QLIKE (H1) conservative. In a reviewer's simulation with pure-noise text it rejected in 0.8% of runs at a nominal 5%; that simulation was not archived. The same has not been checked for the FZ0 test (H2).

## Periods

| Period | Target dates | Use |
|---|---|---|
| Development | 2021-01-04 to 2023-12-13 | Design choices; all results in the research log |
| Holdout | 2023-12-14 to 2026-11-20 | Evaluated once for this design |
| … of which earlier slice | 2023-12-14 to 2025-12-31 | Was the test period of study 1 |
| … of which fresh slice | 2026-01-02 to 2026-11-20 | Never evaluated in any form before |

## Preregistration

The [record](records/volatility_preregistration_20261124.json) was committed before any study 2 model was evaluated on the holdout. (Study 1 had already been evaluated on the holdout's first 500 sessions.) It fixes:

- inputs by hash, including the score table;
- source code by content (Git tree of `src`, and hashes of `pyproject.toml` and `uv.lock`);
- every model constant;
- eligible holdout row counts (computed without reading outcomes);
- hypotheses, test and verdict rule;
- disclosures, including that study 1's failure prompted the design.

**H1 (primary):** the text model has lower QLIKE than the baseline, pooled test.
**H2 (key secondary):** the same for the 5% FZ0 loss.
**Outcome labels:** *confirmed* if H1 has one-sided p < 0.05, both set-ups improve and FZ0 does not worsen; *strong* if H2 also has one-sided p < 0.05. "Strong" names the rule; it is not an effect size.

The evaluation command checks every recorded value against the code and data, writes a marker before computing any outcome, and refuses to run twice.

## Independent review

Two AI reviewer agents, started by the project's own AI agent and working read-only, audited the study before the holdout was opened, using synthetic data only. Neither found look-ahead. Two more reviewed the finished project: one checked every claim against the records, the other the code and operational commands. Findings and fixes are tabulated in the [research log](research-log.md). The reviewers' full reports were not archived, and no human has reviewed the work.

## Limits

See [results.md](results.md#limits).
