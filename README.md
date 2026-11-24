# Financial News and Daily Market VaR

Does financial-news sentiment improve a next-day 95% Value-at-Risk forecast for the S&P 500, beyond market data and news volume? This repository holds a reproducible pipeline that tests the question and the result of the first study.

## Result

**No.** On a locked, preregistered test of 500 forecasts (December 2023 to December 2025), adding FinBERT sentiment changed the 5% quantile loss by −0.06%, with a 95% interval that includes zero.

| Model | Breaches (25 expected) | Mean quantile loss (bp) |
|---|---:|---:|
| Market features | 23 | 11.340 |
| + news counts | 23 | 11.315 |
| + news sentiment | 23 | 11.322 |
| GARCH-t baseline | 26 | 11.890 |

![5% quantile forecasts and realized returns](docs/figures/final_quantiles_and_breaches.png)

The test has low power and the news source (GDELT page titles) is noisy, so this is a qualified negative result, not proof that news is useless. [Results](docs/results.md) has the full picture and [the next methodology](docs/next-methodology.md) explains what a stronger study should change.

## How it works

1. **Market data:** S&P 500 closes from FRED and VIX from Cboe.
2. **News:** GDELT page titles tagged with a stock-market theme and a US location, streamed from the public archive and verified batch by batch.
3. **Sentiment:** a FinBERT model frozen in December 2020 scores each title.
4. **Features:** per trading day, using only information available 30 minutes before the close.
5. **Models:** penalized quantile regression with and without news, against historical simulation, EWMA and GARCH baselines, refitted monthly.
6. **Evaluation:** settings chosen on a development year, protocol preregistered, test period evaluated once.

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
```

```bash
uv run pytest -q
```

```bash
uv run newsvar --help
```

Rebuilding the data and rerunning the study takes about 7 hours on 4 CPUs; see [docs/reproduce.md](docs/reproduce.md).

## Documentation

| Document | Content |
|---|---|
| [docs/results.md](docs/results.md) | Findings, tables, figures, limits |
| [docs/methodology.md](docs/methodology.md) | Forecast definition, data, features, models, evaluation |
| [docs/next-methodology.md](docs/next-methodology.md) | Why the first design was weak and what to build next |
| [docs/architecture.md](docs/architecture.md) | Pipeline, package layout, design rules |
| [docs/reproduce.md](docs/reproduce.md) | Step-by-step commands |
| [docs/records/](docs/records/) | Preregistration and machine-readable results |

## Repository layout

```text
src/newsvar/     pipeline code: data, nlp, features, models, evaluation, study
tests/           synthetic fixtures; no network or real data
scripts/         exploratory diagnostics
docs/            documentation, figures and result records
```

## Data and rights

Raw data, news titles, scores and model weights are never committed; they are rebuilt locally under `data/` and `.cache/`. GDELT, FRED, Cboe and the FinBERT weights each carry their own terms of use.
