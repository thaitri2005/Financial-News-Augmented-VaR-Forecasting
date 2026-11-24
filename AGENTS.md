# Working rules for contributors and coding agents

## Orientation

1. Read [README.md](README.md), then [docs/architecture.md](docs/architecture.md).
2. For anything that touches the study design, read [docs/methodology.md](docs/methodology.md) and [docs/next-methodology.md](docs/next-methodology.md).
3. Inspect the code and Git state. Documentation is not proof that something works.

## Rules that protect the results

- **Never weaken a time rule to make something pass.** A feature may use only information available at its cutoff. A training row may use only an outcome known at the refit time.
- **Missing is not zero.** A failed or absent data interval makes a window incomplete; it is never an empty window.
- **The 2023-12-14 to 2025-12-31 period is used up** as a confirmatory test for the first design. Do not tune on it and call the result a test. A new design needs a new preregistration and a fresh or prospective period.
- **Preregister before evaluating.** Use `newsvar study preregister` and commit the record before `newsvar study evaluate`.
- **Do not commit** secrets, raw data, news text, per-date forecasts, model weights or large generated files. `data/`, `artifacts/` and `.cache/` are Git-ignored for this reason.
- **Free data, CPU, at most 8 GB of project memory.** No paid services without the owner's decision.

## Making changes

1. State what the change should achieve and how it will be checked.
2. Work on synthetic or bounded data first.
3. Run the checks below. Fix failures at their cause.
4. Update the affected documents in the same change. A command shown in the docs must work as written.
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
