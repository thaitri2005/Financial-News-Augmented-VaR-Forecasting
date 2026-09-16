# M1 market foundation cross-document review — 2026-09-16

**Scope:** M1-01/02/03 implementation cadence; README, blueprint, development plan, status, source contract and risks. **Reviewer:** implementing agent in a separate self-review pass; no independent reviewer. **Gate outcome:** raw storage, frozen calendar and retained market-source quality sub-gates pass. M1 dataset/label/news gates remain open.

## Evidence and findings

- The retained FRED and Cboe files were not refreshed. Their saved byte counts, SHA-256 hashes, exact schemas, retrieval time, source rows and valid-value counts match `docs/research/retained_sample_audit.json`. The source-quality importer caps CSV bytes/rows, rejects malformed/duplicate/nonpositive/nonfinite observations, and records FRED placeholders separately.
- The saved 2016-09-15–2025-12-31 XNYS artifact reloaded with its identity and temporal invariants checked. Date-key reconciliation yielded 2,337 origins and 2,337 SP500/VIX observed session values each. Missing SP500, missing VIX on SP500 sessions and off-session SP500 values are zero. All 88 FRED placeholders within the requested date interval are off-session. The 27 extra Cboe values in 2022–2025 are on closures (including 2025-01-09) and never create an index origin. Full dates/source lineage are in [the outcome-blind audit](../research/market_coverage_20260916.json).
- The first market importer is a bounded source-quality admission step. It has not written the blueprint's `market_observations`/`labels` tables, proved original FRED/Cboe release timestamps, or counted usable target-end labels. No final-period return distribution, model score or loss-based example was inspected.
- `37 passed` full fixtures; Ruff lint/format and strict mypy passed. Locked offline `newsvar market audit` passed. Lazy calendar construction keeps saved-snapshot/audit reads free of pandas and `exchange_calendars` imports; an import probe returned `False False` for those modules. Raw-store/calendar reviews remain in [the prior M1 review](2026-09-16-m1-data-foundation.md).
- Cross-document check: README commands run; plan keeps the blueprint separate and adds M1-04B persistence after fixture labels; blueprint §5.6, §10.5, project layout and ADR now match code. The M0 news-source and NLP RAM gates remain open. Low free RAM still postpones 3 GiB normalization and 5 GiB sentiment work, but not this small CSV/JSON quality audit.

## CHG-004 — Bounded market admission before normalization

- **Trigger/evidence:** the retained market CSVs are under 0.5 MiB each and a frozen schedule is 816 KiB. A top-level `exchange_calendars` import made simple saved-schedule reads consume a large dependency graph while live free RAM fell near 1 GiB.
- **Earlier design/problem:** the project layout anticipated separate FRED/Cboe adapters and a normalized market table as one broad market step. Coupling audit reads to calendar construction delayed outcome-blind source-quality checking under the heavy-stage gate.
- **Options/tradeoffs:** keep separate provider modules and a heavy import, which adds duplicated first-pass CSV checks and RAM use; build an unvalidated ad hoc schedule, which weakens calendar identity; or use one bounded source parser plus a fully validated lightweight frozen-snapshot reader, then persist versioned tables later.
- **Decision/rationale:** the shared `ingestion/market.py` parses the two fixed retained schemas, validates the dated audit and matches by XNYS date. `exchange_calendars` imports only when constructing a new schedule. M1-04 proves adjacent label behavior on fixtures; M1-04B persists versioned market/label tables after the 3 GiB live normalization gate. Provider modules can split later if actual versions/release logs warrant them.
- **Authorization/impact:** user's authorized design refinement under the CPU/free-data/≤8 GB project profile. Blueprint version 1.2 §5.6/10.5/layout/ADR-024, plan version 1.1 M1, CLI, contracts, README, tests and status updated. No target, cutoff, availability claim, source universe, split or holdout rule changed.
- **Invalidation/revalidation:** no existing raw file, calendar artifact, feature/model dataset or forecast was rewritten; no downstream output is stale because none exists. M1-04 must reject missing intermediate closes and separate labels from features. M1-04B must prove lineage/versioned replay and rerun live resource checks; an actual provider schema/vintage change reopens source admission.

## Open actions

1. Implement and review M1-04 adjacent-session label construction with small synthetic fixtures. Do not derive labels by shifting rows or bridge missing exchange closes.
2. Defer full normalized market-observation/label persistence (M1-04B) until at least 3 GiB available RAM. Preserve the dated raw sources and frozen calendar.
3. Continue the complete news-feed access/extraction gate independently; no Alpaca credential is present, and free public data remains first. M0 remains open.

**Next cross-document trigger:** three further completed implementation tasks, milestone exit, seven active calendar days, or the specific high-risk preflight before bulk/model/development/final-period actions.
