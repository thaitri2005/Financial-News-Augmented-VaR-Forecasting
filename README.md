# Financial News and Daily Market VaR

A reproducible research project that asks one question: **does financial-news sentiment improve a next-day 95% Value-at-Risk forecast for the S&P 500, beyond market data and news volume?**

- [PROJECT_BLUEPRINT.md](PROJECT_BLUEPRINT.md) is the authoritative research and implementation specification.
- [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) defines milestones and gates; [PROJECT_STATUS.md](PROJECT_STATUS.md) is the live handover record; [AGENTS.md](AGENTS.md) holds the working rules.

## Result (2026-11-24)

**No reliable improvement.** On a locked test of 500 forecasts (target dates 2023-12-14 to 2025-12-31), adding FinBERT sentiment to a quantile model that already had market features and news counts changed the 5% pinball loss by −0.06%, with a 95% block-bootstrap interval of [−0.022, +0.006] basis points. The preregistered claim is not supported.

| Model, 5% tail | Breaches (25 expected) | Mean pinball loss (bp) |
|---|---:|---:|
| Q0 market features | 23 | 11.340 |
| Q1 + news counts | 23 | 11.315 |
| Q2 + news sentiment | 23 | 11.322 |
| GARCH-t (strongest baseline in development) | 26 | 11.890 |
| Historical simulation, 250 days | 30 | 12.179 |

Read this as a **qualified, reduced-power historical-proxy result**:

- The news source is GDELT page titles, a broad and noisy web feed, not a curated vendor headline feed.
- GDELT's archive has gaps; 2020 has only 84.2% complete news windows, so the blueprint's reduced-study split was used (691 training, 250 development, 500 test rows).
- Sentiment was scored on a frozen 27% sample of 3.58 million unique titles.
- News timing is the archive batch time plus 15 minutes, a proxy for when a headline was available.

Full detail: [final review](docs/reviews/2026-11-24-final-evaluation-and-handover.md), [admission review](docs/reviews/2026-11-24-news-admission-and-development-gate.md), [generated tables and figures](docs/research/final_result_tables.md), [preregistration](docs/research/preregistration_20261124.json).

![5% quantile forecasts and breaches on the locked test](docs/figures/final_quantiles_and_breaches.png)

## What is implemented

| Area | Module | State |
|---|---|---|
| Resource preflight | `doctor.py` | working |
| XNYS pre-close calendar and origins | `calendar.py` | working |
| FRED S&P 500 and Cboe VIX admission, labels, versioned Parquet | `ingestion/market.py`, `labels.py`, `datasets.py` | working |
| Baselines: historical simulation, EWMA, GARCH-t, filtered historical simulation | `baselines.py`, `garch.py`, `walkforward.py` | working |
| GDELT title streaming with per-batch verification | `ingestion/gdelt.py` | working |
| Title normalization, relevance, deduplication, window assignment | `news.py` | working |
| Pinned FinBERT loading and resumable bulk scoring | `sentiment.py`, `scoring.py` | working |
| Daily market, count and sentiment features | `features.py`, `feature_table.py` | working |
| Walk-forward quantile models and comparisons | `quantile_models.py`, `experiments.py`, `metrics.py` | working |
| Admission, development, preregistration, final evaluation, report | `study.py`, `report.py` | working |
| Scheduled daily forecasts, runtime memory monitoring | — | not implemented (see status) |

No trading system, dashboard or deployed service exists, and none is planned for this release.

## Setup

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync --locked --python 3.12 --group dev --group ml --group modeling --group risk --group report
```

The PyTorch wheel comes from the CPU index declared in `pyproject.toml`. On Windows the same command works with a Windows uv; earlier Windows bootstrap notes are in the Git history.

## Checks

```bash
uv run --locked pytest -q
```

```bash
uv run --locked ruff check src tests
```

```bash
uv run --locked ruff format --check src tests
```

```bash
uv run --locked mypy src/newsvar
```

Latest result: 106 tests passed; lint, format and strict type checks clean. Tests use synthetic fixtures only and never touch the network or real outcomes.

## Reproducing the study

Everything under `data/`, `artifacts/` and `.cache/` is private and Git-ignored. The commands below rebuild it from public sources. Network access is needed for FRED, Cboe, GDELT and Hugging Face. Identifiers will differ from the recorded ones because FRED serves a rolling ten-year window and the GDELT catalog grows.

1. Market data. Download the two CSVs, record their size and SHA-256 in a manifest shaped like [market_snapshot_20261124.json](docs/research/market_snapshot_20261124.json), then:

```bash
uv run --locked newsvar calendar build --start 2016-11-25 --end 2025-12-31
```

```bash
uv run --locked newsvar market materialize --calendar-path data/calendars/<calendar_id>.json --audit-manifest docs/research/market_snapshot_20261124.json
```

2. News titles. Save `https://data.gdeltproject.org/gdeltv2/masterfilelist.txt` to `data/raw/gdelt/masterfilelist.txt`, then stream the archive. This transfers about 1.1 TiB and keeps about 1.1 GiB; it took 2 h 50 min on 4 CPUs and can be interrupted and rerun.

```bash
uv run --locked newsvar gdelt extract --start 2019-09-01 --end 2025-12-31 --processes 4 --threads 8
```

```bash
uv run --locked newsvar news corpus --start 2019-09-23 --end 2025-12-31
```

3. Sentiment. Place the five files of `ProsusAI/finbert` at revision `5fcfed04a2ca89adf4170ec0a4715103ed7745db` in a directory named after that revision, then score (about 3 h 50 min on 4 CPUs; resumable):

```bash
uv run --locked newsvar news score --corpus data/derived/news/<corpus_id> --model-snapshot .cache/models/ProsusAI_finbert/5fcfed04a2ca89adf4170ec0a4715103ed7745db
```

4. Study. Write `data/study.json` with the paths and the sampling rate printed by the scoring command (fields are listed in the [module contract](docs/development/m1_m5_news_study_contract.md)), then run the stages in order:

```bash
uv run --locked newsvar study admit --output docs/research/news_admission.json
```

```bash
uv run --locked newsvar study develop --admission-record docs/research/news_admission.json --output docs/research/development_record.json
```

```bash
uv run --locked newsvar study preregister --admission-record docs/research/news_admission.json --development-record docs/research/development_record.json --output docs/research/preregistration.json
```

```bash
uv run --locked newsvar study evaluate --registration docs/research/preregistration.json --output docs/research/final_evaluation.json
```

```bash
uv run --locked newsvar study report --admission-record docs/research/news_admission.json --development-record docs/research/development_record.json --final-record docs/research/final_evaluation.json --ledger data/derived/study/final_forecasts.parquet --output docs/research/final_result_tables.md
```

`preregister` refuses to run with uncommitted source changes. `evaluate` refuses to run if inputs differ from the preregistration or a final record already exists. A rerun on the same test period is a replication of this study, not a new confirmatory test.

## Resource use

Designed for CPU and at most 8 GB of project memory. `newsvar doctor --stage sentiment --json` reports whether the current machine passes the preflight for heavy stages (5 GiB available RAM for scoring, 3 GiB for normalization, 15 GiB free disk). Measured wall times are in the [final review](docs/reviews/2026-11-24-final-evaluation-and-handover.md).

## Earlier feasibility evidence

The September 2026 source audits, the feasibility notebook and their dated JSON records remain under `docs/research/` and `notebooks/`. They describe the original Windows laptop; their private snapshots are not in this repository.

## Data and model rights

GDELT, FRED, Cboe and the FinBERT weights each have their own terms. This repository contains code, counts, hashes and aggregate results only. It does not redistribute news text, price series or model weights.
