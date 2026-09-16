# M2-01 baseline review — 2026-09-16

**Scope:** pure historical-simulation and Gaussian-EWMA one-session tail forecasts. **Outcome:** passed on synthetic numerical fixtures; no full historical forecast ledger or model comparison was run.

## Verified behavior

- Historical simulation uses only the supplied final window, NumPy linear tail quantiles, and exact fractional lower-tail expected shortfall. Its fixtures distinguish fractional expected shortfall from a threshold-average shortcut.
- Gaussian EWMA initializes from the first 63 known returns, updates once for each later known return, and produces next-session Gaussian quantile and expected shortfall without a square-root-of-two horizon change.
- All values are decimal simple-return units and lower-tail returns. Forecasts are never sign-flipped, clamped, or filled after a validation error.
- Invalid alpha, short history, NaN input, zero next variance and invalid decay reject with an explicit baseline input error. A later appended return affects only the later forecast call, proving the pure prefix contract.

## Correction during review

The first fixture expected the wrong NumPy linear quantile for alpha 0.375. The implementation returned -0.04375, which is correct because the linear position is 1.125 in the four sorted observations. The test expectation was repaired; no behavioral invariant was weakened.

## Verification and boundary

The full suite now has 57 passing tests. Ruff lint/format and strict mypy pass. This task adds no data-loader, model-run, forecast table, development result, GARCH fit, news feature, or final-period inspection. M2-02 must select labels only by their available-at timestamp, distinguish historical proxy time from actual execution time, and write immutable forecast artifacts.
