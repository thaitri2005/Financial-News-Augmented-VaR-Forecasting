# M2 pre-metrics cross-document gate review — 2026-09-16

**Trigger:** three completed implementation tasks since the prior cross-document review, before joining private forecast attempts to outcomes.

## Checked and retained

- Blueprint target timing, decimal return units, lower-tail sign convention, label availability rule, target-end splits and final-period protection remain unchanged.
- M2-01/02/03 contracts and status evidence agree: the only private ledger covers 2021-2022, contains attempts rather than evaluation, and excludes 2023-2025 target-end rows.
- The GARCH environment pins are documented with the reproduced incompatibility and no broad package upgrade is left implicit.
- README, development plan and status identify M2-04 as synthetic-first and preserve the still-unadmitted news-source boundary.

## Gate decision

Metrics code may be implemented and tested using synthetic forecast/outcome pairs. A private development-only join is allowed only after it enforces exact target-session pairing, common-date masks, outcome identity checks and calendar-aware missing-session transitions. No score, calibration statistic, ranking or model choice may be reported for 2023-2025.

## Next action

Implement the metric primitives and paired-mask fixtures. Update this review pointer and perform a separate task review before any private development metric artifact is created.
