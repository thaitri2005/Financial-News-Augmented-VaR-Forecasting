# M2 close review — 2026-09-16

**Trigger:** M2 causal GARCH/FHS ledger completion and protected metric-input integration.

| Review area | Result |
|---|---|
| Behavior | A converged real causal fit at the first 2021 origin exposed the upstream optimizer's unit-root boundary. The implemented 0.999 persistence constraint is imposed during fitting, then preserved during daily fixed-parameter state updates. |
| Chronology | The ledger selects only labels available by each origin cutoff, refits by calendar month, simulates two steps and uses only the second path return. It covers target-end dates in 2021-2022 only. |
| Failure handling | Initial/refit/state/simulation failures are visible. A refit gets one same-data retry from prior parameters; prior parameters may support only one fallback refit interval. Per-model simulation failures do not hide the other model. |
| Integrity | The full ledger is manifest-addressed and checksum-validated. Its identity includes path count, two-step extraction and persistence cap. |
| Resources | A 10-session 50,000-path pilot took 3.5 seconds. The full 1,006-attempt sequential job took 34.82 seconds after a live diagnostics/normalization resource preflight. |
| Metrics | A protected exact-origin join supplied 503 rows for each market-only model to calibration, transition and paired-pinball calls. Results were intentionally not published. |
| Documentation | Blueprint section 15, M2 contracts, README, plan, status and research evidence now describe the actual implementation and remaining source gate. |

## Decision

M2 passes as the market-only development foundation. It does not admit news data, select a model, publish development scores, or open the 2023-2025 final period. M3 predictive work remains blocked on source admission; M3-01 cache/loader engineering may proceed using synthetic records.
