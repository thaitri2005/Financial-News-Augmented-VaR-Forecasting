# M2 reference gate cross-document review — 2026-09-16

**Trigger:** four completed M2 implementation tasks and transition to the market-only reference report.

| Area | Review conclusion |
|---|---|
| Temporal contract | Target-end membership, prior-session availability proxy, pre-close cutoff and strict no-future-label rule remain intact. |
| Data artifacts | The private M1 market dataset and private M2 2021-2022 attempt ledger are checksum-validated. No 2023-2025 target-end forecast/output has been opened. |
| Baselines | Historical simulation, EWMA, GARCH-t and FHS each have 503 private development attempts. GARCH/FHS use 50,000 paths and a 0.999 fitted-persistence cap. |
| Metrics | Synthetic fixtures protect paired target identity, strict breaches, exact interval behavior and session-aware transitions. The private development join successfully invoked calibration, transitions and paired pinball without disclosing results or generating a ranking. |
| Environment | Core, ML and risk dependency groups are pinned. The risk group’s compatibility constraints are documented. |
| Scope | M2 is useful independent market-only progress. M3 still requires admitted news data despite the completed local FinBERT benchmark. |

## Gate decision

M2-05 may generate an outcome-protected reference report from manifest identities, counts, resource measurements and limitations. It must not disclose forecast values, use final outcomes, publish private development scores, or imply a final-period result. The causal GARCH/FHS runner and protected metric join now satisfy the M2 gate; M3 remains blocked by source admission.
