# M2-03 GARCH-t and filtered historical simulation contract

## Environment

The optional risk group pins arch 7.2.0, Statsmodels 0.14.5 and Pandas 2.2.3. A direct import check found that arch 7.2.0 is incompatible with the initially resolved Statsmodels 0.15/Pandas 3 stack because Pandas changed a decorator signature used by arch. The pins are part of the model environment identity and are not an incidental repair.

## Model and path contract

Fit zero-mean GARCH(1,1) with Student-t innovations on eligible decimal returns multiplied by 100. Convert all simulated paths and forecasts back to decimal simple-return units. Require converged optimization, finite nonnegative omega/alpha/beta, persistence no greater than 0.999, and degrees of freedom strictly above two. Each origin gets a deterministic seed derived from the experiment seed, model ID and origin session.

The ARCH library permits its ordinary optimizer to settle on a numerical unit-root boundary. A 2021 causal fit did so despite reporting convergence. The implementation therefore supplies the same GARCH(1,1) likelihood with an explicit persistence cap of 0.999. The cap keeps the fitted model stationary, is part of the experiment identity, and must be reported in every resulting ledger; it is not a post-fit parameter edit.

Simulate exactly two one-session returns. The first is the unobserved origin-session return; the forecast distribution is only the second path column. Do not sum the columns or use the first column. For parametric GARCH-t, the custom Student-t random generator divides draws by sqrt(nu/(nu-2)) so shocks have unit variance. For filtered historical simulation, arch bootstrap samples standardized in-sample residuals; it uses the same two-step extraction and path count.

## Failure and resource policy

An initial failed/non-finite/invalid fit yields a visible failure, never a synthetic fallback. At later monthly refits, retry once on the same eligible history using the previous valid parameters as optimizer starting values. If it still fails, use the previous valid parameters for only that one refit interval and label the affected forecasts `fallback_previous_refit`; two consecutive fallback intervals are prohibited. State-update and per-model simulation errors are separate visible statuses, so one failed FHS call cannot erase a successful parametric GARCH forecast.

The immutable development ledger records the capped persistence, two-step extraction, model IDs and simulation-path count in its identity before execution. The first synthetic benchmark uses 50,000 paths, one process, and records elapsed/RSS without values or performance ranking. The later 200,000-path stability study is a separate M2-05 evidence item.
