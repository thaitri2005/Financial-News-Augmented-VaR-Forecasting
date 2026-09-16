# M1-04B market persistence review — 2026-09-16

**Scope:** immutable observation/label persistence and right-edge recovery. **Reviewer:** implementing agent, separate review pass. **Outcome:** passed; this is the first versioned market dataset, not a feature, forecast, or research-result release.

## Evidence reviewed

- The materializer created an extended 2,338-origin XNYS snapshot through 2026-01-02 and verified all 2,337 original origin records exactly before publication.
- Dataset 7819b4c29e1822c6829bf7ea2f5ec8570ba4995eb7f9e4d017722412701a1d8a reloads with manifest identity, file-size, SHA-256 and Parquet row-count checks: 4,792 observations, 2,336 labels and two exclusions. The [outcome-blind dataset record](../research/market_dataset_20260916.json) gives hashes and counts.
- Study inclusion is target-end based. The December 30→31 2025 label is now eligible using the January 2 cutoff under the declared proxy. December 31→January 2 is excluded by horizon; January 2 is excluded because no later cutoff exists. No placeholder becomes a return.
- A Windows fsync defect found during test execution was repaired by reopening staged files read/write before fsync. Tests prove exact extension, idempotent replay, target-edge policy and checksum detection after a deliberately corrupted Parquet file.

## CHG-006 — Typed Arrow/Parquet dataset publication

Apache Arrow 25.0.1 is pinned for typed Parquet serialization. A one-writer same-volume staging directory is fully validated, then renamed once to its content-derived directory. This is sufficient for the small bounded local slice and avoids a database service. A changed raw source, parser, calendar, schema, availability policy or Arrow version yields a distinct dataset identity; downstream work must rerun against it.

This updates blueprint ADR-026/version 1.5, plan version 1.3, README, status, the persistence contract and the dated evidence record. It does not change the target formula, historical-availability assumption, news admission gate, or any final-period outcome.

## Verification

Targeted synthetic checks passed before review: 28 tests across dataset, labels, market and calendar modules. The release check reruns the full suite, Ruff lint/format, strict mypy, locked offline materialization and the new outcome-blind inspection command. The resulting commands and outcomes are recorded in project status.
