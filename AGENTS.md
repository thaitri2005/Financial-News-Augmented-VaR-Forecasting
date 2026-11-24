# Working rules for contributors and coding agents

## Orientation

1. Read [README.md](README.md), then [docs/architecture.md](docs/architecture.md).
2. For anything that touches the study design, read [docs/methodology.md](docs/methodology.md), [docs/research-log.md](docs/research-log.md) and [docs/roadmap.md](docs/roadmap.md).
3. Inspect the code and Git state. Documentation is not proof that something works.

## Rules that protect the results

- **Never weaken a time rule to make something pass.** A feature may use only information available at its cutoff. A training row may use only an outcome known at the refit time.
- **Missing is not zero.** A failed or absent data interval makes a window incomplete; it is never an empty window.
- **Target dates from 2023-12-14 to 2026-11-20 are used up** as a confirmatory test. Do not tune on them and call the result a test. A new design needs a new preregistration and a later or prospective period.
- **Design on development data only** (target dates through 2023-12-13) and write every variant you try into the research log.
- **Preregister before evaluating.** Use `newsvar vol preregister`, commit the record, then run `newsvar vol evaluate` once.
- **Ask for an independent review before opening a holdout.** Both pre-test reviews of study 2 found problems that would have weakened the result.
- **The forecast log is append-only.** Never rewrite an entry in `data/forecasts/log.jsonl`.
- **Do not commit** secrets, raw data, news text, per-date forecasts, model weights or large generated files. `data/`, `artifacts/` and `.cache/` are Git-ignored for this reason.
- **Free data, CPU, at most 8 GB of project memory.** No paid services without the owner's decision.

## Making changes

1. State what the change should achieve and how it will be checked.
2. Work on synthetic or bounded data first.
3. Run the checks below. Fix failures at their cause.
4. Update the affected documents in the same change: the research log for anything tried, the methodology and architecture for anything changed, the roadmap when a step is finished. A command shown in the docs must work as written.
5. A changed rule (relevance, deduplication, features, split) creates a new versioned artifact. Do not edit an old one in place.

## Checks

```bash
uv run pytest -q
```

```bash
uv run ruff check src tests
```

```bash
uv run ruff format --check src tests
```

```bash
uv run mypy src/newsvar
```

Tests use synthetic fixtures only. They must not need the network, credentials or real data.
