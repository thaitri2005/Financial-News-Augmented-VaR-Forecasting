# M1 data foundation review — 2026-09-16

**Scope:** temporal dataset foundation increments. **Reviewer:** implementing agent, separate self-review pass. **Cross-document milestone gate:** pending until market/calendar/label parts pass.

## M1-01 raw commit and restart behavior

- Design evidence: [raw commit contract](../development/m1_raw_commit_contract.md).
- Implementation: typed `RawManifest`, `CommittedArtifact`, `RawStore`, immutable SHA-256 IDs, bounded page writes, staged directory publication, checksum/schema validation and restart from a valid stage.
- Windows synthetic fixtures proved directory rename works for this project root and that crash boundaries before payload manifest, before rename, and after rename are observable/recoverable. A corrupt commit fails instead of being reused. Illegal source IDs and credential/page-token keys are rejected.
- Separate review found a valid staged artifact with conflicting replay metadata was being renamed before comparison. Changed recovery to compare row count, completeness, source terms and adapter version **before** publication, and added a regression fixture.
- Verification after that change: `8 passed` targeted provenance tests, Ruff passed. Strict mypy and format checked in the final M1-01 review. Production adapters and their cursor/completeness semantics remain unimplemented.
- Resource scope: small synthetic payloads only, 32 MiB API-page cap. No network/source refresh, model inference or full dataset evaluation.

### CHG-002 — Atomic raw directory protocol

- Trigger: blueprint required a raw payload and manifest to become visible together with restart behavior, but did not specify the on-disk atomic boundary.
- Decision: stage both files together and rename the complete directory under `committed/`; derive a stable raw ID from source/request/payload hashes, with attempt time excluded. Reads revalidate checksum/metadata; partial stages are identifiable but invisible.
- Alternatives: two separate file renames permit a partially visible artifact; a mutable catalog alone would complicate one-writer local recovery. A source-file streaming adapter is deferred because the first consumer is a bounded API page.
- Affected: blueprint §10.2 and ADR-023, raw contract, production modules, tests and README. No existing research snapshot/manifests were rewritten. Source admission, market labels and forecasts are not invalidated.
- Revalidation: real source adapter must prove cursor advancement after commit and input/output totals; M1 integration fixtures will exercise that boundary.

## M1-02 calendar contract

- Design evidence: [calendar contract](../development/m1_calendar_contract.md), official exchange-calendar project, tested package version `4.13.2`, dated NYSE early-close reference.
- Implementation: XNYS scheduled open/close, previous/next edge sessions, pre-close origin fields, exact news-window eligibility, SHA-256 calendar identity with exchange-calendars and tzdata versions, immutable save/load and CLI build/inspect.
- Verification: `7 passed` targeted calendar tests (early close, July holiday, January 9 special closure, DST, boundaries, saved-file corruption, forged new hash with wrong margin, CLI); Ruff and strict mypy passed. Mypy suppresses only the untyped upstream `exchange_calendars` import; local contracts remain typed and runtime-validated.
- Real dated artifact: `data/calendars/0fa86aa24e4551cc2346bb00b069a3e733797edd35bfa87d8440bdff7e345b9c.json`, 816,013 bytes; 2,337 origins from 2016-09-15 through 2025-12-31. CLI inspect reloaded it and verified identity. The source FRED/Cboe files have not yet been imported into this schedule.
- Review: loader verifies margins and consecutive origin links even if someone recomputes a filename hash around altered timestamps. The calendar file has no outcome values. Calendar-package coverage was observed through 2027-09-16; out-of-range requests fail instead of extrapolating holiday patterns.
- Resource observation: available RAM fell to about 1.0 GiB after the full calendar run. Subsequent larger normalization/inference is paused; only small fixture/source-quality checks may continue until live preflight clears the gate.

### CHG-003 — Frozen exchange-session identity

- Trigger: blueprint required one exchange calendar but did not define a portable schedule artifact/identity.
- Decision: hash actual origin UTC timestamps, requested bounds, cutoff/issue profile and package/tzdata versions; save/reload this immutable schedule. FRED/Cboe adapters and labels will consume the frozen artifact, not derive business days independently.
- Alternatives: fixed New York UTC offsets fail at DST; pandas business-day rules miss exchange holidays and special closures; deriving the schedule separately in each module risks disagreement.
- Affected: blueprint §7.2, calendar module/CLI, README, tests, plan M1 and this review. No source payload, feature dataset, model or locked-test result was changed.
- Revalidation: compare the chosen schedule against retained market dates and official notices during M1-03; any mismatch is a source/calendar decision, never silent row-position alignment.
