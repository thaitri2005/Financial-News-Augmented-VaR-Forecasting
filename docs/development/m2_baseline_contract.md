# M2-01 market baseline contract

## Scope

This increment implements two pure numerical reference methods: rolling historical simulation and zero-mean Gaussian EWMA. It begins with decimal simple-return sequences supplied by callers and synthetic fixtures. It does not yet query the private label table, create walk-forward forecasts, fit GARCH, use news, or inspect final-period results.

Every returned forecast is a lower-tail return quantile and optional expected shortfall in decimal simple-return units. A negative quantile is a loss-side forecast; no value is sign-flipped or clamped for presentation. The caller supplies only returns whose labels are already available at its cutoff. The baseline module never silently fills missing observations or bridges sessions.

## B0 historical simulation

The primary window is 250 eligible one-session returns, with 1,000 as a later common-support variant. The quantile uses NumPy linear interpolation at tail probability alpha. Expected shortfall is the exact average of the lowest alpha probability mass: sort returns, consume whole observations below alpha times n, then add the fractional next observation. This is explicitly different from averaging all observations below an interpolated quantile.

## B1 Gaussian EWMA

Use zero mean, lambda 0.94 and a 63-return initialization window. Initialize the conditional variance from the mean squared initialization returns. Update once per subsequent already-known return. The resulting next-session variance produces a Gaussian alpha quantile and left-tail expected shortfall. No square-root-of-two factor is applied because the forecast is one session, not a two-session cumulative return.

## Failure and version policy

Reject non-finite values, invalid alpha, insufficient history, invalid lambda, non-positive variance and wrong horizon rather than returning a fallback. Tests include hand values, fractional ES, causal-prefix behavior and validation failures. Any later integration must carry the immutable market dataset ID, label availability selection and model configuration identity; a changed dataset/target/availability policy invalidates its forecasts.

## M2-02 ledger publication

The first development-only ledger freezes target-end sessions from 2021-01-01 through 2022-12-31. For every origin, it selects labels only when their origin is earlier and their availability timestamp is at or before that origin cutoff. Each calendar month is marked as a refit boundary. The private Parquet ledger stores attempts, not evaluated outcomes; it distinguishes ready from insufficient-history attempts and has a content-derived run ID plus checksum manifest.

The executed run ID is 1e1b9ce5e173a29196edbc04ae6f04c8d5835e948228dee5ba74f2f6fed1cd05. It contains 1,006 attempts across 503 development target-end sessions: 503 historical-simulation and 503 Gaussian-EWMA attempts, all ready. There are 50 marked monthly-refit rows, one per model at each of 25 calendar-month boundaries. No 2023–2025 target-end row, forecast value, realized outcome, score or ranking appears in public evidence.
