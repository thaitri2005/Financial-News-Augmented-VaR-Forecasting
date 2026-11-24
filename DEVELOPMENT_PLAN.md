# Agent development and delivery plan

**Version:** 2.0 · **Created:** 2026-09-15 · **Updated:** 2026-11-24 · **Scope:** implement the accepted blueprint incrementally.

**Start here on resumption:** [PROJECT_STATUS.md](PROJECT_STATUS.md). **Scientific authority:** [PROJECT_BLUEPRINT.md](PROJECT_BLUEPRINT.md). **Mandatory agent workflow:** [AGENTS.md](AGENTS.md).

## 1. Readiness decision and delivery contract

The blueprint is ready for implementation. Its conditional choices are deliberate evidence gates, not missing permission to begin. News-source access/completeness, full Windows ML dependency compatibility, and actual NLP throughput remain unverified. Begin with the independent local foundation and source-admission work; do not build forecasting conclusions on an unadmitted feed.

The product is a reproducible daily S&P 500 price-return VaR experiment and a small local batch system. Success includes a defensible negative or inconclusive finding. The first deliverable is trustworthy chronology and correct market-only forecasts; news forecasting follows after its own gates. A dashboard, profitable strategy, commercial deployment, and favorable news result are not acceptance criteria.

This plan is written for an AI agent that may resume with limited conversational context. Durable files must answer: what is true, what is next, why that task is ready, how to verify it, and what evidence would require a change. Do not rely on memory or prior chat as the only task record.

### 1.1 Authority without competing sources of truth

| File/artifact | Owns | Update trigger |
|---|---|---|
| `PROJECT_BLUEPRINT.md` | Target, source admission, information timing, features, models, architecture, resource and scientific acceptance rules | Any semantic/design change |
| `DEVELOPMENT_PLAN.md` | Stage dependencies, task contracts, review/recovery/change process | Changed sequence, delivery strategy, or gate procedure |
| `PROJECT_STATUS.md` | Actual task states, active work, evidence, blockers, next executable action | Every completed/paused work increment |
| `AGENTS.md` | Persistent instructions for agents | Changed mandatory working practice |
| `README.md` | Current implemented capabilities and runnable setup/check commands | A capability or command becomes available/changes |
| `docs/reviews/` | Dated milestone/deviation/review evidence and unresolved findings | A substantive review or decision |
| Run/data manifests and lockfile | What actually ran, exact inputs/environment and artifacts | Each execution/dataset/environment version |

Do not copy the whole blueprint into tickets or maintain multiple live status tables. Reference its section/ADR and record only task-specific acceptance. If code and documents disagree, report and resolve the inconsistency; neither silently overrides the other. User instructions remain the highest project authority.

## 2. Planning method for an agent

### 2.1 Plan the near term precisely

Maintain a detailed ready queue for the next two or three increments. Later milestone tasks have concrete outputs and exit rules but are refined after upstream evidence arrives. Each increment should deliver one coherent behavior, investigation result, or defect repair that can be checked independently. Split tasks that cannot be reviewed without several unrelated subsystems.

Use stable task IDs `M0-01`, `M1-01`, etc. Subtasks append a letter; never reuse an ID for a different problem. Bugs use `BUG-001`; material deviations use `CHG-001`. Store the full brief for the active task and the next ready task in status; archive material conclusions in reviews rather than growing an unbounded session diary.

Work in progress: one implementation task and at most one independent bounded investigation. No delegation is implied. Resource-intensive jobs remain sequential even if another tool could run concurrently.

### 2.2 Task state machine

```text
planned -> ready -> active -> review -> done
                    |          |
                    +-> blocked+-> active (fix required)
done -> reopened -> ready/active (new evidence or defect)
planned/ready -> deferred or cancelled (reason retained)
```

- `planned`: dependencies or acceptance still need refinement.
- `ready`: inputs/access exist; acceptance and bounded scope are defined.
- `active`: currently being implemented/investigated.
- `review`: implementation and relevant checks exist; documentation/behavior review remains.
- `done`: acceptance evidence, review, and documentation agree.
- `blocked`: a specific missing dependency prevents that task; record work that can continue.
- `reopened`: prior completion was invalidated; record affected outputs and previous evidence.
- `deferred`/`cancelled`: explicit scope decision, never disguised as completion.

Milestones are `not_started`, `in_progress`, `gate_review`, `passed`, or `reopened`. A blocked task does not automatically block its whole milestone. Milestone gates report `pass`, `fail`, or `not_evaluated`; conditional scope reductions require a named decision and a separate valid gate, not a vague “mostly passed.”

### 2.3 Required task brief

```text
ID / title / owner:
Outcome and reason:
Blueprint sections / ADRs:
Inputs and prerequisite evidence:
Allowed files / scope:
Out of scope for this increment:
Steps and bounded resource/request budget:
Acceptance checks (observable; not "looks good"):
Failure/recovery and artifact invalidation:
Documentation to update or review:
Actual results / evidence / limitations:
State and next action:
```

Use this for substantial tasks; a small defect can reference an existing contract rather than duplicate it. Plans estimate complexity (`S`, `M`, `L`) and uncertainty, not fictitious AI working hours. Split large tasks after the investigation clarifies them. Blueprint human-hour estimates remain context, not agent deadlines or proof of progress.

## 3. Milestone map and dependencies

| Stage | Outcome | Depends on | Exit decision |
|---|---|---|---|
| M0 Foundation and admission | Runnable core, persistent workflow, resource check, chosen data/study scope | Existing blueprint/public audit | Environment and source gates explicitly recorded |
| M1 Temporal dataset | Immutable ingestion, calendar, versions, cleaned tables, causal feature/label boundary | M0 core; production news requires admitted source | Dataset contract/chronology/completeness gate |
| M2 Market-risk reference | Correct B0–B3 and walk-forward forecast ledger | M1 market/calendar/labels subset | Numerical and chronology reference gate |
| M3 Sentiment dataset | Fixed encoder, cache, audited sentiment, daily M/C/S features | M1 admitted news and M0 NLP resource gate | Text/model/feature admission gate |
| M4 Development experiments | Limited comparisons, robustness, chosen configuration | M2 and M3; enough eligible rows | Preregistration frozen before final outcomes |
| M5 Locked research evaluation | Auditable final forecasts, calibration/uncertainty, conclusion | M4 signed local review record | Reproducible research release |
| M6 Local operation and handover | Manual replay; optional scheduled shadow run, recovery/monitoring | M5 for scientific promotion; operational fixtures earlier | Research-only or shadow-use acceptance |

Independent progress is allowed: market calendar/labels and M2 need not wait for news access; ingestion persistence can use synthetic responses; NLP domain work can use admitted prototype text while its predictive use remains prohibited. A fixture implementation does not close the real-source gate.

### M0 — Foundation, source admission, and measured limits

**Entry:** blueprint plus retained public audits. **Principal risk:** access assumptions or a large ML environment become hidden prerequisites.

| Task | Concrete increment | Acceptance / evidence | Dependency |
|---|---|---|---|
| M0-01 | Agent plan, status, documentation/review rules | Agent can resume without chat; scope/status/authority consistent; cross-document review recorded | Existing blueprint |
| M0-02 | Minimal packaged Python core and locked local environment | Isolated patched Python 3.12; `newsvar --help`; lockfile; explicit installed dependency scope | M0-01 |
| M0-03 | Read-only `newsvar doctor` and resource-policy tests | Reports RAM/free disk/timezones; stage readiness and exit codes correct at boundaries; no data/network/secret scan | M0-02 |
| M0-04 | Select news access route and source card | GDELT bounded extraction or free Alpaca pilot; rights, quotas, interval/filter/version semantics, continuity evidence; named source/study outcome | Blueprint §5–6; actual access |
| M0-05 | ML environment and NLP benchmark | Pinned historical FinBERT files, tested Windows lock groups, 1,000 then sustained 10,000 headline timing/RSS; admission decision | Sufficient live resources; suitable text |
| M0-06 | M0 gate review | Core passes; source and resource evidence determines admitted scope; unresolved items cannot be called passed | M0-01–05 or explicit market-only branch |

**Source spike limits:** inherit blueprint §5–6 exactly: zero paid budget, two-focused-hour GDELT extraction specification, conservative scan/result caps, capped Alpaca requests if credentials become available. Record actual attempts and bytes. Do not repeat the already completed FNSPID prefixes or Yahoo full-file audit without a new question. Do not create cloud accounts or assume credentials exist. Request only the specific access needed after preparing a concrete pilot; continue independent tasks meanwhile.

**M0 scope branches:**

- Full news study: selected source meets temporal/coverage/rights/resource gates.
- Reduced news study: qualifying interval meets the blueprint's reduced sample thresholds; freeze revised split without inspecting outcomes.
- Market-only plus news prototype: source gate fails or remains unavailable; market system proceeds, news remains non-confirmatory.

**Exit evidence:** core verification report, environment lock, source card/admission or documented branch decision, resource benchmark or explicitly blocked NLP gate. The core sub-gate may pass while overall M0 remains open. Never mark news readiness from `doctor` alone.

### M1 — Immutable data and temporal correctness

| Task | Concrete increment | Acceptance / evidence | Dependency |
|---|---|---|---|
| M1-01 | Typed manifests, hashes, atomic commit/resume | Interrupted/repeated synthetic pages neither lose records nor expose partial artifacts | M0 core |
| M1-02 | Versioned XNYS schedule and origin contract | Regular/early close, DST, holiday, weekend and boundary fixtures; UTC conversions verified | M0 core |
| M1-03 | Retained FRED/Cboe source-quality admission | Existing snapshots can be parsed without refetch; 27 extra VIX closed dates explicitly excluded; source/calendar dates reconciled | M1-01/02 |
| M1-04 | Separate label materializer | Known fixture return/units; missing session not bridged; label available only after both prices | M1-03 |
| M1-04B | Extended-calendar and normalized market/label persistence | Verify original/extended schedule overlap, recover final 2025 target-end label; frozen source/vintage IDs, observation/availability metadata, versioned tables and lineage reloaded | M1-03/04; 3 GiB normalization gate |
| M1-05 | Admitted news adapter and interval ledger | Bounded pagination, inclusive edges, 429/retry, repeated cursor, empty vs failed intervals, restart tests | M1-01; source admission |
| M1-06 | Version/timestamp normalization and quarantine | 100 stratified rows audited; original times retained; later payload never backdated | M1-05 |
| M1-07 | Cleaning, language/relevance, chronological dedup | Cause-specific reconciliation; no ticker multiplication; fixed rules and future-append invariance | M1-06; notebooks 01/03 |
| M1-08 | Dataset card and alignment gate | Exact rows/intervals/hashes, exclusions, provenance class, coverage grid, notebook 04 temporal checks | All applicable M1 tasks |

Explore parsing/cleaning in notebooks 01–04 before promoting accepted rules into package functions. The delivered notebook 00 is a starting audit, not proof of M1 completion. Use bounded samples; inspect source metadata across candidate dates outcome-blind. Source-specific schema changes create versioned data, not manual edits to old files.

The M1-03 quality report is a lightweight, bounded read of retained files and a previously frozen schedule. It does not materialize the blueprint's `market_observations` table and therefore is allowed as a small diagnostic below the 3 GiB normalization gate. M1-04 first proves label/adjacency behavior on synthetic fixtures; M1-04B performs versioned market/label table persistence only after the live normalization gate passes. The shared initial `ingestion/market.py` source parser may later split into provider-specific adapters when schemas, vintages, or release tracking warrant it. This sequencing keeps market-only correctness work available while news-source access and larger RAM remain open.

M1-04's first bounded quality run deliberately leaves two 2025 right-edge label availability times unknown. In M1-04B, build a new immutable XNYS snapshot from 2016-09-15 through 2026-01-02, compare every overlapping origin record with the first snapshot, and use the following 2026-01-02 cutoff for the 2025-12-30 label. Freeze study/scoring membership by target-end session through 2025-12-31; the 2025-12-31 origin targets 2026 and stays outside the declared final period. Preserve the older audit/calendar and record the new dataset version before any model use.

**Market sub-gate:** M1-01–04B can pass independently and unlock M2. **News sub-gate:** M1-05–08 plus source admission unlock predictive news use. Record both separately. Any feature/label access violation blocks downstream experimentation immediately.

### M2 — Market-only reference and backtesting

| Task | Concrete increment | Acceptance / evidence |
|---|---|---|
| M2-01 | Historical simulation and Gaussian EWMA | Hand-calculated quantile/ES/sign fixtures, causal warmup, explicit units and horizon |
| M2-02 | Monthly walk-forward runner and immutable forecasts | Only available labels selected; no shuffled split; actual execution vs simulated origin distinct |
| M2-03 | GARCH-t and filtered historical simulation | Standardized innovations; simulate two steps and extract second one-session return; convergence/fallback/Monte Carlo checks |
| M2-04 | Metrics and common-date comparison engine | Pinball and breach calculations, sparse/undefined tests, missing-session transitions, paired-mask integrity |
| M2-05 | Reference notebook/report and gate | All baseline outputs reproducible from fixed inputs; resource measurements; failure counts; no final-period optimization |

Use synthetic distributions and development dates. Model failures remain in the attempt ledger. Validate the simple baselines before adding GARCH complexity; a model with plausible-looking output but wrong horizon does not pass. The market-only pipeline is a useful independently releasable increment if news remains blocked.

### M3 — Frozen sentiment and daily features

| Task | Concrete increment | Acceptance / evidence |
|---|---|---|
| M3-01 | Immutable encoder loader and resumable cache | Exact SHA/config/tokenizer/weights, correct label map, deterministic record alignment, failed/incomplete batches recover |
| M3-02 | Domain/truncation/resource audit | Blueprint 200-headline audit, truncation and inference gates; FP32 baseline, INT8 only if justified and equivalent |
| M3-03 | M/C/S feature builders and assignments | Nineteen specified features, fixed session lookbacks, retained vs scored denominators, zero news vs missing feed, lineage |
| M3-04 | Full feature materialization and news gate | Cache reuse avoids repeated scoring; ≤8 GB allowance and stricter thresholds; appended future news leaves prior outputs unchanged |

No raw embeddings, body models, fine-tuning, current constituent weights, or future-price/entity enrichment. M/C/S comparisons use the same origin mask. Prototype text can test parsers/throughput but cannot silently become the admitted study corpus.

### M4 — Development and preregistration

| Task | Concrete increment | Acceptance / evidence |
|---|---|---|
| M4-01 | Linear Q0/Q1/Q2 with training-only preprocessing | Correct percentage-point fitting/decimal outputs; saved feature order/imputer/scaler; future extreme rows cannot affect fit |
| M4-02 | Declared chronological search | 36 fold/config runs for preferred split, or 18 for GDELT alternative; same budget by feature group; failures/cost recorded |
| M4-03 | Required timing/count/VIX/source robustness | Rebuild/refit sensitivities rather than shifting predictions; report tradeoffs and missing origins |
| M4-04 | Optional small tree challenger | Only if core is stable and measured budget remains; declared 48/24 maximum fold/config runs; no broad search |
| M4-05 | Freeze final experiment protocol | Dataset/split/feature/model/config/lock/code hashes, primary comparison, scores, uncertainty, exclusions, reporting and failures fixed |

Readiness includes sufficient training/validation/test origins after exclusions. If sample gates fail, return to source/scope decisions before evaluating final outcomes. The primary comparison remains 5% Q2 versus Q1. Review blueprint §§16–17 and the full risk register before enabling locked evaluation. A dated local review record establishes the gate; it does not require another user permission for already authorized experiments.

### M5 — Locked evaluation and conclusion

| Task | Concrete increment | Acceptance / evidence |
|---|---|---|
| M5-01 | Execute frozen final walk-forward protocol | Preregistration predates evaluation; eligible earlier test outcomes may enter scheduled refits; future outcomes never select methods |
| M5-02 | Paired uncertainty and calibration | Exact common counts, bootstrap block policy, breach/transition diagnostics, sparse 1% limitations, failures/crossings |
| M5-03 | Rebuild report from predictions | Notebook 08 clean rerun; tables and figures derive from immutable prediction/outcome joins; no hidden fits in reporting |
| M5-04 | Research release review | Honest positive/negative/uncertain/data-no-go conclusion; incremental and strongest-baseline comparison; limitations and reproduction verified |

A defect repair after opening the test must preserve earlier evidence and rerun all affected outputs. A scientific redesign converts that final period into development data; plan later/prospective confirmation. Never silently retune a model because a final result is disappointing.

### M6 — Operation and handover

| Task | Concrete increment | Acceptance / evidence |
|---|---|---|
| M6-01 | Manual local daily run and stale-data policy | Data state frozen at cutoff; issue deadline obeyed; no forecast backdating; validated fallback identified |
| M6-02 | Recovery, monitoring and compatible rollback | Single-writer lock, actual resource monitoring, interrupted-run recovery, model/feature schema compatibility |
| M6-03 | Optional Windows scheduling/shadow log | 20 consecutive scheduled-session attempts, latency and failures; laptop wake/power constraints documented |
| M6-04 | Reproducible handover | Clean setup/fixture replay, docs review, source re-access/backup limits, capability matrix and known issues |

Research-only delivery can omit scheduling by explicit scope decision; it still needs reproducible manual execution. Twenty sessions demonstrate operations only, not VaR predictive skill. Local release does not authorize publishing raw data or deploying a service.

## 4. Quality and documentation gates

### 4.1 Definition of ready

A task is ready when the relevant blueprint contract is known, required inputs/access exist, scope and acceptance are explicit, resource/network bounds are set, and the artifact/review owner is identified. If an uncertainty is the task itself, use a bounded investigation with a decision output. Do not classify a task as blocked merely because it requires learning a library.

### 4.2 Definition of done

All applicable items must be satisfied:

1. Intended behavior exists, including failure handling and provenance where relevant.
2. Checks match the risk: temporal/data/model invariants have meaningful tests; trivial formatting edits need only inspection.
3. Relevant tests, lint/type checks and runnable examples pass, or a limitation keeps the task open.
4. Resource use is measured for resource-sensitive behavior; estimated budgets are labeled estimates.
5. A distinct review pass inspects the final diff/behavior, including downstream consequences.
6. Affected docs are updated and linked; status includes exact evidence and limitations.
7. No hidden credentials, future data, false completion claim, or unresolved blocker invalidates acceptance.
8. Next action is concrete and its prerequisites are visible.

Avoid implementation-mirroring tests and elaborate CI for empty scaffolds. Add fixtures around observed failures, temporal boundaries, resource thresholds and recovery. Tests requiring credentials or full models are opt-in, separate from ordinary checks. Repeating an unchanged expensive test is justified only by changed inputs/code or an unresolved concern.

### 4.3 Mandatory documentation reviews

**Every increment:** update or explicitly review relevant blueprint/README/plan/status sections. A change that makes an existing command/example false is incomplete until the docs are fixed.

**Cross-document review:** required at each milestone exit, after three completed implementation tasks, or after seven calendar days of active development since the last such review, whichever occurs first. When development was idle, review on the next session. This is a workflow trigger, not an always-running scheduled service.

**High-risk gate review:** always before bulk news acquisition, a new inference backend/checkpoint, development experiments, or the locked final period. Inspect current source terms/limits when performing access-dependent actions.

Review checklist:

- Does README describe actual capabilities and commands, with implemented/planned labels?
- Do blueprint semantics, configurations, code, tests and notebook conclusions agree?
- Are source access, timestamps, data masks, resource thresholds and experiment gates still valid?
- Are active tasks/dependencies/status/evidence accurate and no completed task silently invalidated?
- Do new findings change the risks, scope, estimates or next tasks?
- Are obsolete assumptions removed from active guidance but preserved in dated history?

Record date, scope, reviewer role, evidence, findings, actions/owners, and gate outcome in `docs/reviews/YYYY-MM-DD-topic.md`. State self-review honestly. Update the last-review pointer and the completed-task counter in status. Do not create five duplicate reports for one coherent milestone review.

## 5. Change, defect, and replanning protocol

### 5.1 Change classification

| Class | Example | Required response |
|---|---|---|
| Implementation fix | Parser bug while preserving intended contract | Reproduce, targeted test, repair, affected rerun, docs clarification if needed |
| Design refinement | Different storage batch size or justified language rule | Record evidence/alternatives; update relevant blueprint/config; benchmark/revalidate affected behavior |
| Scientific change | New target/cutoff/source universe/split/feature/scoring | Version blueprint/protocol; identify invalidated artifacts; re-evaluate holdout status before rerun |
| Scope/access/budget change | Paid feed, different instrument, remote service | Prepare concrete tradeoff/cost/impact; obtain user authorization if not already provided |

Routine in-scope design refinements may be decided by the agent using evidence. Do not freeze a poor blueprint choice to avoid editing documents. Conversely, a faster implementation is not a sufficient reason to weaken the information contract or source gate.

### 5.2 Required deviation record

For material changes, add a `CHG-nnn` entry to a dated review:

```text
Trigger and evidence:
Existing decision / problem:
Options considered and tradeoffs:
Decision and rationale:
Authorization basis, if relevant:
Affects: blueprint sections, task IDs, config/schema versions, data/model/report IDs
Invalidated artifacts and downstream tasks:
Revalidation / rollback:
Updated next milestones and gate state:
```

Preserve old artifacts. Mark affected downstream tasks `reopened` or outputs `stale`; never keep a “done” badge while its inputs are known wrong. Rebuild the smallest correct dependency closure plus rolling-history context. A corrected source timestamp may invalidate features, models and reports across many dates even if one parser line changed.

### 5.3 Failure and blocker response

1. Classify failure: access, source quality, environment, resource, code, or experimental evidence.
2. Capture a bounded reproducer and exact error/counts without secrets.
3. Form a hypothesis, change one relevant cause, run a targeted check.
4. After two failed attempts with the same approach, change method: inspect the lower layer, isolate a smaller fixture, consult primary documentation, or choose the documented alternative. Record what was disproved.
5. If external input is truly required, record the precise missing input, affected tasks, evidence, and smallest user action. Continue ready independent work.
6. On recovery, recheck the dependency and resume from committed artifacts; do not restart the whole project.

For research no-go, deliver the validated market-only branch and explain the news limitation. For inconclusive signal, finish the declared evaluation; do not launch an unbounded feature search. For resource overruns, reduce concurrency/batch size, then optional scope, before removing correctness checks.

## 6. Agent session and handover protocol

### Start

Read status and applicable instructions; inspect current files/changes; verify that the recorded next action remains valid; identify any user steering; check live resources before heavy work. Do not reset existing work or regenerate immutable source evidence as routine setup.

### During work

Keep one active task explicit. Communicate meaningful findings and remaining uncertainty. Use a small reproducible example before a bulk run. Keep experiments outcome-blind until their allowed stage. If a change crosses task boundaries, document the dependency and either split the task or replan it.

### End or interruption

Update status with: completed checks and paths, active/blocked task, partial artifacts and resumable command if any, known failures, last review, and the next one or two executable actions. If work is unfinished, say so. Never call the milestone passed merely because the current response is ending. Do not auto-commit, publish, or deploy simply to create a milestone marker.

### Completion reporting

Summarize what now works, what was verified, which milestone/task advanced, material limitations, and the next step. User-facing summaries may be short because the complete agent handover lives in the repository.

## 7. Initial execution slice

**This implementation session:** complete M0-01, implement/test the minimal package and read-only resource doctor (M0-02/03), review all affected docs, and record an honest M0 status. This is a coherent first delivery, not authorization inferred for an overnight corpus/model run. Broader implementation is authorized by the user and proceeds in later increments under these gates.

**Next ready work:** M0-05 passed its bounded local NLP benchmark using engineering-only Yahoo titles; it does not admit that corpus for predictive research. The bounded complete-news-feed admission pilot still awaits access. M2-01 may now begin after the M1/M0 cross-document review. Do not block market-data foundation work on Alpaca credentials.

**State on 2026-11-24:** M0–M5 are complete under three recorded changes (CHG-001 streaming GDELT extraction, CHG-002 reduced-study split, CHG-003 sampled sentiment scoring). M6 is closed as research-only: M6-01 deferred, M6-03 cancelled for v1, M6-04 done. The M0-04 BigQuery and Alpaca pilots were never executed and remain optional follow-up studies. The stage commands and their gates are in the [news study contract](docs/development/m1_m5_news_study_contract.md).

The detailed next queue and actual progress belong in `PROJECT_STATUS.md`, not in this static plan.

## 8. Plan revision history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-15 | Agent-oriented milestone/task contracts, evidence gates, continuous docs review, replanning/recovery protocol, and initial implementation slice |
| 1.1 | 2026-09-16 | Separated bounded market source admission and fixture label construction from RAM-gated normalized-table persistence; updated next ready queue after M1-01/02/03 |
| 1.2 | 2026-09-16 | Added explicit right-edge calendar extension and target-end filtering acceptance to M1-04B after M1-04 quality evidence |
| 1.3 | 2026-09-16 | Recorded completed Arrow/Parquet market persistence, checksum reload, and the open-resource NLP benchmark queue; M2 now depends on M1-04B |
| 1.4 | 2026-09-16 | Recorded CPU-only FinBERT environment and successful bounded 1,000/10,000-title benchmark; predictive news-source admission remains open |
| 1.5 | 2026-09-16 | Closed the market-only M2 gate with immutable causal GARCH/FHS development attempts, a bounded stationary persistence constraint, and a protected metric-input integration; M3 remains source-gated |
| 1.6 | 2026-09-16 | Added M3-01's local pinned-loader and resumable content-addressed cache implementation; its live inference smoke test remains gated on available RAM |
| 1.7 | 2026-09-16 | Added M3-03's synthetic causal M/C/S feature functions and adversarial quality/window fixtures; real feature materialization remains source-gated |
| 1.8 | 2026-09-16 | Added M4-01's pinned training-only linear quantile adapter, preprocessing persistence and synthetic future-schema fixtures; all data-dependent experiments remain gated |
| 1.9 | 2026-09-16 | Added M4-02's fixed 36-run preferred and 18-run GDELT-alternative linear manifests; M3/M4 data-dependent tasks remain gated on source admission |
| 2.0 | 2026-11-24 | Resumed in a cloud container; completed source admission by streaming GDELT, the sentiment dataset, development search, preregistration and the locked evaluation; closed M6 as research-only; recorded CHG-001–003 |
