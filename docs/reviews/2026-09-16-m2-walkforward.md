# M2-02 walk-forward ledger review — 2026-09-16

**Scope:** private, development-only historical/EWMA forecast-attempt ledger. **Outcome:** passed. No evaluation or final-period run was performed.

- The ledger selects an outcome only when its origin precedes the forecast origin and its recorded availability is no later than the origin cutoff. Synthetic fixtures prove exclusion of both the current target and a prior target with delayed availability.
- The 2021-2022 private ledger has content ID 1e1b9ce5e173a29196edbc04ae6f04c8d5835e948228dee5ba74f2f6fed1cd05 and checksum-validated 1,006 rows: 503 ready attempts for each fixed baseline. It has 50 explicitly marked monthly-refit rows.
- It records cutoff and model identity; forecast values and outcomes remain private. It contains no 2023-2025 target-end session. No scoring, tuning, ranking or model selection occurred.
- 59 tests pass, together with Ruff lint/format and strict mypy. The artifact manifest reload validates identity, file checksum and row count.

M2-03 may add GARCH only after its separate simulation/convergence contract and fixture review. M2-04 must build metrics on a protected evaluation join, never by retroactively changing these attempts.
