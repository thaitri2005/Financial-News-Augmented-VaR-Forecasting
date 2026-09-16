# Foundation review — 2026-09-15

**Scope:** M0-01, M0-02 and M0-03. **Reviewer:** implementing agent, separate self-review pass; no independent reviewer. **Outcome:** core foundation sub-gate passed; overall M0 remains open.

## CHG-001 — Add an agent execution plan

- Trigger: user authorized implementation beginning with a detailed, adaptable agent-oriented development plan, and explicitly clarified that the plan must be added rather than replacing the blueprint.
- Decision: preserve `PROJECT_BLUEPRINT.md` as the scientific/architectural source of truth; add `DEVELOPMENT_PLAN.md`, `AGENTS.md`, and `PROJECT_STATUS.md` for execution, mandatory working rules and live handover respectively.
- Alternatives: putting live task states into the blueprint would mix specification with progress; a separate large project-management service would add a dependency without helping this local single-agent project.
- Blueprint version 1.1 changes only companion links and current implementation-status wording. Target, timing, source rules, models, features and statistical gates remain unchanged.
- Continuous documentation review is required every increment and across documents at milestone exit, every three completed tasks, or seven active calendar days. Material deviations reopen affected tasks/artifacts instead of silently changing the intended contract.
- Authorization: explicit user request; no additional permission needed for these local additions.
- Invalidated scientific artifacts: none. Existing source audits/snapshots and notebook outputs were preserved.

## Implementation reviewed

- `pyproject.toml` and `uv.lock`: minimal CLI/resource dependencies plus development tools; no premature Torch, numerical-model stack, data services or cloud dependencies.
- Runtime: patched CPython 3.12.14 under the project cache and isolated `.venv`; uv 0.12.15 in a separate local bootstrap environment. Core installation resolved 22 packages including the local package.
- `newsvar doctor`: read-only RAM, disk, process-tree RSS and timezone preflight; diagnostics/normalization/sentiment stages; JSON output and defined exit codes.
- `tests/test_doctor.py`: synthetic boundary/failure tests independent of laptop load. Runtime observations are not hard-coded test expectations.
- README distinguishes actual commands from planned capabilities and the original notebook environment from the minimal core environment.

## Checks and results

Commands were run from the repository root using the local `.venv` or local uv with `--locked --offline`.

| Check | Result |
|---|---|
| `python -m pytest -q` | **10 passed**, 0.71 s reported test runtime |
| `ruff check src tests` | Passed |
| `ruff format --check src tests` | Passed; 5 files formatted |
| `mypy src/newsvar` | Passed; 4 source files, strict mode |
| `newsvar --help` | Passed; only implemented `doctor` command advertised |
| `newsvar doctor --json` | Valid JSON; requested diagnostics exit 0; all stage readiness/reasons present |
| Synthetic CLI low-memory test | Diagnostics exit 0; sentiment exit 3; invalid stage exit 2 |
| Documentation/artifact checks | 6 documents reviewed, 67 local links verified, all 25 blueprint sections preserved, 7 additional development milestones; TOML/runtime pin valid |

Live preflight `2026-09-15T16:04:32.650950Z` recorded:

```text
Python:               3.12.14
Installed RAM bytes:  16780767232
Available RAM bytes:   3059970048
Free disk bytes:      75871645696
Doctor tree RSS:         27160576
Missing timezones:    none
Measurement errors:   none
Diagnostics:          ready
Normalization:        blocked (<3 GiB available)
Sentiment:            blocked (<5 GiB available)
```

This is a resource snapshot, not a benchmark of sentiment/modeling or a permanent machine-state assertion. Source admission is not part of `doctor` and remains open.

## Review findings and resolutions

1. Initial formatting check found two long CLI strings. Wrapped them and reran lint, format and type checks; all passed.
2. Review clarified that a diagnostics pass cannot imply heavy-stage readiness. JSON reports each stage and limitations; README/status repeat the meaningful boundary, not a blanket “ready” claim.
3. Resource reads fail closed on measurement errors; tests cover unavailable measurements, timezones, runtime mismatch and exact byte thresholds. A vanished child is omitted from the instantaneous RSS; unknown access failures are reported.
4. The initial uv Python installation created an unused user-level versioned launcher. Its creation in this session was verified; it did not resolve the local runtime and was removed. The project interpreter and environment remain intact. Future setup documents `--no-bin --no-registry` and an absolute install directory, avoiding that side effect. System Python and shell PATH were not replaced.
5. Existing research scripts are not retroactively linted or migrated into the production core. Their dated environment/evidence remains explicit; later migration must preserve snapshot identity.
6. No source or predictive artifact is declared ready from a core smoke test. No temporal pipeline/model tests are claimed to exist yet.

## Cross-document review

Reviewed README, blueprint implementation-status/architecture/resource/verification/PM sections, development plan, agent instructions and project status together. Roles are explicit, source gates remain conditional, current commands work, required documentation/review cadence is persistent, and next task acceptance is concrete.

**Open:** real source admission, ML environment and resource benchmark, immutable ingestion, calendar and label contracts, continuous runtime guard, model evaluation, CI and scheduling. The blueprint is not replaced or frozen against evidence-supported future improvements.

**Next action:** M1-01 on synthetic fixtures; prepare calendar work and bounded source admission separately. Recheck live memory before heavy jobs. No further model/source downloads are required to start the next local foundation task.
