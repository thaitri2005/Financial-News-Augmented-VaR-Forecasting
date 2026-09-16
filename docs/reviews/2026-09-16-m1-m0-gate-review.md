# M1 market and M0 environment gate review — 2026-09-16

**Trigger:** milestone exit and three completed implementation tasks since the prior cross-document review. **Reviewer:** implementing agent, self-review across blueprint, plan, README, status, contracts, evidence and runnable commands.

## Gate decisions

| Gate | Decision | Evidence and boundary |
|---|---|---|
| M1 market foundation | Passed | Immutable raw sources, frozen/extended XNYS calendars, source-quality audit, versioned observation/label tables and checksum reload are complete. Dataset 7819b4c29e1822c6829bf7ea2f5ec8570ba4995eb7f9e4d017722412701a1d8a has 4,792 observations, 2,336 labels and two explicit boundary exclusions. |
| M0 local NLP resource | Passed for engineering | CPU FinBERT 1,000/10,000-title benchmark passed below the 6 GiB RSS limit with fixed revision/hash evidence. This only supports future local feature engineering. |
| M0 news source admission | Still waiting access | GDELT local catalog/cost package is complete but needs a user-owned free BigQuery sandbox or free Alpaca credentials. Yahoo remains engineering-only. |
| M2 market-only reference | Ready | M1-01 through M1-04B satisfy its input contract. Begin simple historical/EWMA fixtures before GARCH or any predictive news work. |
| M3 sentiment features | Blocked on source admission | Hardware/model gate is satisfied, but there is no admitted complete historical feed. |

## Cross-document checks

- Blueprint versions 1.5 and 1.6 match the implemented Parquet and CPU benchmark decisions. The target, pre-close cutoff, historical availability proxy, target-end membership and source restrictions did not change.
- Development plan version 1.4 correctly makes M2-01 ready while retaining the news-admission dependency for M1 news work and M3.
- README commands for materialization and dataset integrity inspection execute successfully. Benchmark evidence and its engineering-only limitation are linked.
- Status names M0-05 as complete after this review and promotes M2-01. M0 itself is not closed because M0-04 is an external-access dependency.
- All stored public evidence is aggregate/outcome-blind where needed. Raw market values, Yahoo titles, model weights, credentials and forecasts remain outside tracked documentation.

## Verification

After the market persistence change, 49 tests passed; Ruff lint and format checks and strict mypy passed. Locked offline market materialization replayed its existing immutable dataset, and integrity inspection succeeded. The ML group imported CPU PyTorch 2.6.0 and Transformers 4.49.0 and both bounded benchmark runs completed. No model was trained, no feature table was produced, and no final-period result was inspected.

## Next decision

Proceed with M2-01 as a separate bounded task. M0-04 needs user-provided access only when the free source-admission pilot is ready to execute; no paid service or account creation is authorized.
