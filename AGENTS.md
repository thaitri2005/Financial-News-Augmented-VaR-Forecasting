# Agent operating instructions

This repository implements a financial-news VaR research project. Work autonomously within the user's authorized scope, using the following persistent protocol.

## Start every work session

1. Read [PROJECT_STATUS.md](PROJECT_STATUS.md): active task, evidence, blockers, and next action.
2. Read the relevant milestone and task in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).
3. Read the applicable sections of [PROJECT_BLUEPRINT.md](PROJECT_BLUEPRINT.md), then inspect actual files and Git state. Documentation is not proof that code or a test exists.
4. Select one ready, bounded implementation task. Record it as active before changing behavior. Do not repeat completed work without changed inputs, a defect, or a specific review reason.

## Authority and scope

- User instructions take precedence. The blueprint owns scientific/architectural semantics; the development plan owns execution workflow; project status owns live task state. Commands documented as implemented must actually work.
- Implement the smallest complete, verifiable increment. Do not scaffold future services or add models merely because they appear in the roadmap.
- Source admission and resource checks are hard dependencies of the stages they protect. Missing credentials block dependent ingestion, not independent local engineering.
- Free data first, CPU, at most 8 GB project RAM; follow the stricter runtime thresholds in the blueprint. No paid services, trading, external publication, or messages to others are included.
- Never put secrets, private raw data, weights, or large generated outputs in Git. Preserve dated source snapshots; do not rerun legacy collectors over delivered evidence casually.
- Do not create sub-agents solely because this is an agent-oriented plan. Delegate only when the user or applicable higher-priority instructions explicitly authorize it.

## Required task completion loop

1. State acceptance criteria and inspect dependencies.
2. Implement or investigate on bounded data. Preserve before/after evidence.
3. Run the relevant checks. Fix failures at their cause; never weaken a temporal invariant to make a test pass.
4. Perform a separate review pass of behavior, chronology, resources, error handling, and documentation. A self-review is not independent review.
5. Update affected documentation **in the same work increment**. Record either the actual doc changes or an explicit explanation that semantics/docs were reviewed and remain accurate.
6. Update `PROJECT_STATUS.md` with task state, checks and results, evidence paths, open issues, and an executable next action. A task cannot be `done` without evidence and a documentation review.

## Required review cadence

- Every behavior/config/schema/source change: review affected blueprint/runbook sections before marking the task done.
- Every milestone exit, every three completed implementation tasks, or seven calendar days of active development since the previous cross-document review—whichever occurs first: review README, plan, status, applicable blueprint sections, risks, commands, and unresolved decisions together. If inactive, do it on resumption; no background timer is required.
- Before bulk ingestion, new model inference, development experiments, or opening the locked test: perform the relevant gate review even if the ordinary cadence is not due.
- Store substantive gate/review outcomes under `docs/reviews/`; update the last review pointer in status. Avoid a separate report for every trivial edit.

## Replanning and recovery

Reopen a task when new evidence invalidates it; retain the earlier evidence and reason. Identify affected downstream datasets/models/reports and mark them stale before rerunning. Routine fixes and evidence-supported blueprint changes within accepted scope do not require repeated permission. Budget changes, external account access, and externally consequential actions require the appropriate user authorization.

Use the deviation/change procedure in the development plan. After two failed attempts at the same approach, change the investigation method and record the hypothesis/evidence. Do not repeat downloads, broad test suites, or retries without a reason. This is an investigation trigger, not permission to abandon useful independent work.

## Current verification entry point

See README for implemented commands and local environment setup. Run targeted tests during development and the declared full foundation checks at task/milestone review. No network or real news credentials belong in ordinary unit/fixture tests.
