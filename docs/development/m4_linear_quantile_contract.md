# M4-01 linear quantile contract

Q0/Q1/Q2 use the same adapter with an explicitly supplied frozen feature order. Training rows must have exactly that schema; nulls are allowed, but non-finite values are rejected. The training-only pipeline is median imputation, constant-column removal, then `StandardScaler`. Its fitted objects, retained feature names, tail level and L1 penalty are stored together atomically for each refit.

Targets enter `QuantileRegressor(quantile=tail_alpha, alpha=l1_penalty, solver="highs", fit_intercept=True)` in percentage-point units. Predictions leave the adapter in decimal simple-return units. `tail_alpha` and the L1 penalty are distinct inputs. There is no random split, early stopping, test access or implicit feature selection.

This implementation has synthetic fixtures only. Fitting it to real M/C/S rows, tuning penalties or comparing Q0/Q1/Q2 remains blocked until the source-backed feature gate is passed.
