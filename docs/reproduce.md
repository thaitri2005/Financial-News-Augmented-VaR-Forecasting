# Reproduce the studies

Everything under `data/`, `artifacts/` and `.cache/` is private and Git-ignored. These steps rebuild it from public sources. You need network access to FRED, Cboe, Yahoo, GDELT, Hugging Face and the PyTorch CPU wheel index, about 15 GB of free disk, and roughly 9 hours of processing on 4 CPUs. Most of that is FinBERT scoring, which the text model does not need but the secondary sentiment terms do.

Run every command from the repository root. Identifiers will differ from the recorded ones: FRED serves a rolling ten-year window and the GDELT catalog grows daily.

## 1. Environment

```bash
uv sync --locked
```

```bash
uv run newsvar doctor --stage sentiment
```

## 2. Market data

```bash
uv run newsvar market fetch
```

```bash
uv run newsvar market fetch-ohlc
```

Use the first date in the downloaded FRED file as `--start`.

```bash
uv run newsvar calendar build --start 2016-11-25 --end 2026-11-20
```

## 3. News titles

```bash
uv run newsvar gdelt catalog
```

The extraction streams about 1.3 TiB and keeps about 1.2 GiB. It commits per day; rerun the same command to resume. `--max-seconds` stops cleanly after a time budget.

```bash
uv run newsvar gdelt extract --start 2019-09-01 --end 2026-11-23 --processes 4 --threads 8
```

```bash
uv run newsvar news corpus --start 2019-09-23 --end 2026-11-23
```

## 4. Sentiment scores

```bash
uv run newsvar news fetch-model
```

Scoring commits every 5,000 titles; rerun to resume.

```bash
uv run newsvar news score --corpus data/derived/news/<corpus_id> --sampling-rate 0.27 --model-snapshot .cache/models/ProsusAI_finbert/5fcfed04a2ca89adf4170ec0a4715103ed7745db
```

## 5. Study 2 (volatility and text)

Create `data/volatility_study.json`:

```json
{
  "calendar_path": "data/calendars/<calendar_id>.json",
  "fred_csv": "data/raw/market/fred_sp500.csv",
  "vix_csv": "data/raw/market/cboe_vix.csv",
  "ohlc_json": "data/raw/market/yahoo_gspc_daily.json",
  "etf_json": "data/raw/market/yahoo_spy_daily.json",
  "corpus": "data/derived/news/<corpus_id>",
  "scores_root": "data/derived/scores",
  "model_snapshot": ".cache/models/ProsusAI_finbert/5fcfed04a2ca89adf4170ec0a4715103ed7745db",
  "sampling_rate": 0.27,
  "development_start": "2021-01-04",
  "development_end": "2023-12-13",
  "holdout_start": "2023-12-14",
  "holdout_end": "2026-11-20",
  "fresh_start": "2026-01-02"
}
```

Run the stages in order. Commit the development record, then the registration, before evaluating.

```bash
uv run newsvar vol develop --output docs/records/volatility_development.json
```

```bash
uv run newsvar vol preregister --development-record docs/records/volatility_development.json --output docs/records/volatility_preregistration.json
```

```bash
uv run newsvar vol evaluate --registration docs/records/volatility_preregistration.json
```

```bash
uv run newsvar vol report --registration docs/records/volatility_preregistration.json
```

`evaluate` writes `docs/records/volatility_evaluation_<id>.json` and refuses to run twice for one registration. A rerun over the same holdout replicates this study; it is not a new confirmatory test.

## 6. Study 1 (sentiment quantile regression)

Study 1 needs the versioned market dataset and its own settings file.

```bash
uv run newsvar market materialize --calendar-path data/calendars/<calendar_id>.json
```

Create `data/study.json` with `market_dataset`, `calendar_path`, `corpus`, `corpus_start` (`2019-09-23`), `scores_root`, `model_snapshot`, `sampling_rate`, `feature_root` and `study_end`, then:

```bash
uv run newsvar study admit --output docs/records/news_admission.json
```

```bash
uv run newsvar study develop --admission-record docs/records/news_admission.json --output docs/records/development_record.json
```

```bash
uv run newsvar study preregister --admission-record docs/records/news_admission.json --development-record docs/records/development_record.json --output docs/records/preregistration.json
```

```bash
uv run newsvar study evaluate --registration docs/records/preregistration.json --output docs/records/final_evaluation.json
```

## 7. Daily operation

```bash
uv run newsvar update
```

```bash
uv run newsvar forecast
```

`update` takes about 5 minutes once the history exists and writes `data/operations.json`. `forecast` takes about 5 minutes and appends to `data/forecasts/log.jsonl`.

## 8. The PDF report

Needs a LaTeX installation with TikZ.

```bash
cd report && latexmk -pdf report.tex
```

## Checks

```bash
uv run pytest -q
```

```bash
uv run ruff check src tests
```

```bash
uv run mypy src/newsvar
```
