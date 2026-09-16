# M3/M4 source-gate cross-document review — 2026-09-16

**Trigger:** completion of three source-independent M3/M4 implementation increments.

| Area | Review conclusion |
|---|---|
| M3 model/cache | Loader/cache tests and local snapshot fingerprint are implemented. The live 5 GiB sentiment gate remains unmet. |
| M3 features | M/C/S calculations match the fixed causal windows and preserve incomplete-feed, empty-window and coverage semantics. No real news rows were materialized. |
| M4 adapter | The linear quantile adapter fits only supplied training rows, persists preprocessing and converts between percentage-point fitting and decimal outputs correctly. |
| M4 protocol | Preferred and GDELT-alternative linear candidate counts are fixed at 36 and 18. No search was executed. |
| Source/final-period controls | No source was admitted; Yahoo/GDELT feasibility files remain excluded from predictive use. No 2023-2025 rows, scores or model-selection outputs were opened. |
| Dependencies | `scikit-learn==1.6.1` is pinned in the optional `modeling` group. Core/risk/ML/modeling checks remain locally reproducible. |

## Gate decision

M3-01 is waiting only on live available RAM; M3-02/03 materialization and M3-04 require a source admission decision. M4-03 onward requires source-backed development rows. Continue only source-independent quality work until one of those gates changes.
