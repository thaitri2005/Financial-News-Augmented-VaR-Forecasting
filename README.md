# Financial News and Daily Market VaR

Start with [PROJECT_BLUEPRINT.md](PROJECT_BLUEPRINT.md), the authoritative research and implementation specification.

The **additional** [development plan](DEVELOPMENT_PLAN.md) defines milestones, agent task contracts, gates, and continuous review. [PROJECT_STATUS.md](PROJECT_STATUS.md) is the live progress/handover record; [AGENTS.md](AGENTS.md) makes documentation updates and regular reviews mandatory.

## Current state

Research/design and initial public-source feasibility inspection are complete. The implementation now provides a locked Python core, a resource-doctor CLI, an immutable raw-page store, frozen XNYS calendars, a retained-market-source quality audit, and a private versioned Parquet market/label dataset with explicit availability. Complete news-source admission, full ML setup, and forecasting remain future work. The design targets this Windows laptop, free data first, CPU execution, and at most 8 GB project RAM.

- [Executed feasibility notebook](notebooks/00_environment_and_sources.ipynb): timestamp evidence, market joins, development-period EDA, GDELT titles, Yahoo collection diagnostics.
- [Initial public-source audit](docs/research/public_source_probe.json): bounded FRED/Cboe/FNSPID probes.
- [Retained sample audit](docs/research/retained_sample_audit.json): market files and five GDELT archive batches.
- [Yahoo collection audit](docs/research/yahoo_collection_audit.json): 70,974 records across seven original source files.
- [GDELT catalog pilot](docs/research/gdelt_catalog_pilot_20260916.json): capped public archive-listing evidence for two complete UTC days; no archive payloads were downloaded.

Fourteen raw payloads are retained locally under Git-ignored `data/raw/feasibility_20260915/`, totaling approximately 148 MiB. API credentials are not needed to inspect these existing samples. No model has been fitted and no forecast improvement has been established.

## Implemented core: setup and verification

The core uses Python **3.12.14**, `uv.lock`, and the local `.venv`. Only CLI/resource/time-zone dependencies and development checks are installed; research/NLP dependencies will be added in their own stages. uv itself is bootstrapped separately at version 0.12.15. No shell activation is required.

Existing local setup, from this repository root:

```powershell
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar --help
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar doctor --json
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar doctor --stage sentiment --json
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline pytest -q
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline ruff check src tests
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline ruff format --check src tests
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline mypy src/newsvar
```

`doctor` defaults to small diagnostics. Exit `0` means the requested preflight passed; `3` means a resource/environment gate failed; `2` means invalid command input. JSON reports every stage, with byte measurements and reasons. Normalization needs at least 3 GiB available RAM; sentiment needs 5 GiB; the disk reserve is 15 GiB. Heavy-stage RSS must not exceed 6 GiB. A diagnostics pass does not mean inference is ready.

This is a read-only snapshot of the current command and its children. It does not check source access, download a model, validate the future ML environment, inspect credentials, or continuously enforce memory limits on another job. Recheck before each heavy stage; runtime monitoring will be implemented later.

Fresh Windows setup, using an existing Python installation to bootstrap uv (network required):

```powershell
python -m venv .cache/bootstrap
.\.cache\bootstrap\Scripts\python.exe -m pip install --only-binary=:all: uv==0.12.15
$newsvarPythonDir = Join-Path (Get-Location) '.cache/python'
.\.cache\bootstrap\Scripts\uv.exe python install 3.12.14 --install-dir $newsvarPythonDir --no-bin --no-registry
.\.cache\bootstrap\Scripts\uv.exe sync --locked --python .cache/python/cpython-3.12.14-windows-x86_64-none/python.exe --group dev
```

Use the project-local uv path above, or a compatible `uv` already on PATH. `--no-bin --no-registry` keeps managed-Python installation from creating user-level launchers/registration. Installed global Python packages are not reused by `.venv`. Primary references: [uv installation](https://docs.astral.sh/uv/getting-started/installation/) and [locked synchronization](https://docs.astral.sh/uv/concepts/projects/sync/).

Latest core evidence: [foundation review](docs/reviews/2026-09-15-foundation.md). These core checks do not claim that future ingestion/model contracts are implemented.

The package also contains a bounded [raw artifact store](src/newsvar/provenance.py) for future adapters. It commits a complete payload/manifest directory atomically, validates hashes on read, and recovers interrupted/repeated synthetic page writes. Its [storage contract](docs/development/m1_raw_commit_contract.md) defines what it guarantees. No production provider adapter, pagination ledger, or raw-file streaming is implemented yet; the store has no standalone CLI command.

The [calendar module](src/newsvar/calendar.py) now builds/loads versioned XNYS origin grids. Its [contract](docs/development/m1_calendar_contract.md) and saved 2016–2025 snapshot define the exact pre-close cutoffs and target sessions. These commands work in the locked environment:

```powershell
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar calendar build --start 2016-09-15 --end 2025-12-31
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar calendar inspect data/calendars/0fa86aa24e4551cc2346bb00b069a3e733797edd35bfa87d8440bdff7e345b9c.json
```

The saved schedule has 2,337 origins; its file is private under ignored `data/`. `calendar build` needs a bounded library import and does not read prices or news. If current free RAM is under the blueprint's heavy-stage threshold, postpone full grids and use small fixture intervals.

The [retained market importer](src/newsvar/ingestion/market.py) verifies the dated FRED/Cboe snapshots against their original byte counts, SHA-256 hashes, exact CSV schemas, and row counts. The saved-calendar reader is lightweight; this date/value audit does not require pandas or a 3 GiB normalization preflight:

```powershell
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar market audit --calendar-path data/calendars/0fa86aa24e4551cc2346bb00b069a3e733797edd35bfa87d8440bdff7e345b9c.json
```

It reports 2,337 FRED/VIX closes on the 2,337 exchange sessions, zero missing session closes, and 27 VIX rows on closed 2022–2025 dates. The [dated coverage report](docs/research/market_coverage_20260916.json) lists excluded dates, FRED placeholders, out-of-grid counts, and raw source lineage. It reports no final-period returns. This is source-quality evidence, not a normalized observation table, availability-vintage proof, usable label count, or full data gate. [Market contract](docs/development/m1_market_contract.md).

The [label builder](src/newsvar/labels.py) uses actual adjacent SP500 closes and an explicit later usable time for each close. Its historical-proxy quality command prints counts/reasons/lineage only:

```powershell
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar labels audit --calendar-path data/calendars/0fa86aa24e4551cc2346bb00b069a3e733797edd35bfa87d8440bdff7e345b9c.json
```

The [dated label audit](docs/research/label_quality_20260916.json) contains 2,335 labels with availability and two year-end exclusions caused by the first saved calendar's right edge. M1-04B passed a live ≥3 GiB RAM preflight, extended the immutable calendar through 2026-01-02, and produced the first private market dataset. The declared study membership is selected by target-end session; no CLI report displays return values. [Label contract](docs/development/m1_label_contract.md).

Materialize or validate the versioned tables with:

```powershell
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar market materialize --calendar-path data/calendars/0fa86aa24e4551cc2346bb00b069a3e733797edd35bfa87d8440bdff7e345b9c.json
.\.cache\bootstrap\Scripts\uv.exe run --locked --offline newsvar market inspect data/derived/market/7819b4c29e1822c6829bf7ea2f5ec8570ba4995eb7f9e4d017722412701a1d8a
```

The materialization produced dataset `7819b4…a1d8a`: 4,792 retained observations, 2,336 eligible labels, and two explicit boundary exclusions. It is backed by Apache Arrow 25.0.1 Parquet files, a checksum-verified manifest, and the extended calendar `628049…fe5e4`. See the [dataset evidence](docs/research/market_dataset_20260916.json) and [persistence contract](docs/development/m1_market_persistence_contract.md).

## Reproduce the existing audit

Run from the repository root with the original research Python environment, whose versions are recorded below; notebook dependencies are not installed in the minimal core `.venv`. The first three commands may use the network and overwrite dated diagnostics/snapshots; source snapshots can change. Preserve the delivered evidence first. The Yahoo inspector reuses files already present. The notebook verifies retained hashes and uses local files only.

```powershell
python docs/research/probe_public_sources.py
python docs/research/collect_feasibility_sample.py
python docs/research/audit_yahoo_collection.py
python docs/research/build_audit_notebook.py
python -m nbconvert --to notebook --execute --inplace notebooks/00_environment_and_sources.ipynb --ExecutePreprocessor.timeout=120
```

The collectors use bounded responses/streaming. Preserve the delivered dated snapshots and audit records before intentionally refreshing them. The future production pipeline will use immutable run directories and a locked environment as specified in the blueprint.

The collectors use Python's standard library. Notebook authoring/execution additionally needs `nbformat`, Jupyter/`nbconvert`, and Matplotlib. See [research execution environment](docs/research/execution_environment.json) for the versions used in this audit; this is an observed environment record, not the future production lockfile.

## Prepared GDELT feasibility pilot

The raw GDELT archive route is not practical for a multi-year local backfill: two complete catalog-listed days alone total roughly 0.46–0.71 GiB compressed each. The project now has a capped [catalog probe](docs/research/probe_gdelt_catalog.py), its [dated evidence](docs/research/gdelt_catalog_pilot_20260916.json), and a [free BigQuery sandbox pilot contract](docs/development/m0_gdelt_pilot_contract.md). The next execution needs a user-owned, no-billing BigQuery sandbox; it starts with schema metadata and a 10 GiB-capped dry run, not title export or a bulk job.

## Next step

See the ready queue in [PROJECT_STATUS.md](PROJECT_STATUS.md): the public-news access/extraction pilot still needs external free-sandbox access, while the now-open 5 GiB NLP gate has permitted the bounded local benchmark. Documentation updates and reviews are part of task acceptance, not a final cleanup phase.

The benchmark passed with the pinned CPU-only FinBERT environment: 1,000 titles ran at 47.60 titles/second with 0.76 GiB peak RSS; the sustained 10,000-title run completed at 33.56 titles/second with 0.90 GiB peak RSS. Both repeated-prefix checks matched. It establishes local engineering viability only; the Yahoo collection remains unadmitted for predictive research. See the [benchmark contract](docs/development/m0_finbert_benchmark_contract.md), [1,000-title evidence](docs/research/finbert_benchmark_1000_20260916.json), and [10,000-title evidence](docs/research/finbert_benchmark_10000_20260916.json).

The first market-only references are also implemented as tested pure calculations: 250-session rolling historical simulation and Gaussian EWMA, both in decimal simple-return units with explicit expected shortfall conventions. They currently run only against synthetic fixtures; a causal, immutable walk-forward forecast ledger is the next increment. See the [baseline contract](docs/development/m2_baseline_contract.md) and [review](docs/reviews/2026-09-16-m2-baselines.md).

The ledger is now materialized privately for the 2021-2022 development period: 1,006 checksum-validated attempts across 503 target-end sessions, with no 2023-2025 rows or public forecast/outcome values. See the [outcome-blind ledger evidence](docs/research/m2_development_ledger_20260916.json).

The [M2 reference gate](docs/research/m2_reference_gate_20260916.json) confirms the market-only foundation: historical simulation, EWMA, GARCH-t and FHS each have 503 private 2021-2022 development attempts. The [GARCH ledger evidence](docs/research/m2_garch_development_ledger_20260916.json) records the causal 50,000-path implementation and protected metric-input check. No score, ranking or final-period evaluation has been published.

M3 now has a pinned local FinBERT loader and atomic content-addressed score-cache implementation, tested only with synthetic records. The [encoder/cache contract](docs/development/m3_encoder_cache_contract.md) preserves the 5 GiB live-inference gate and the separate news-source admission requirement.

M4 also has a synthetic-only training adapter for the declared linear quantile models plus fixed 36-run/18-run chronological search manifests. It cannot run against predictive data until the source-backed feature gate passes; see the [search-plan contract](docs/development/m4_search_plan_contract.md).
