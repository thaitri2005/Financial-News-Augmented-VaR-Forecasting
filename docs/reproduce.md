# Reproduce the study

Everything under `data/`, `artifacts/` and `.cache/` is private and Git-ignored. These steps rebuild it from public sources. You need network access to FRED, Cboe, GDELT, Hugging Face and the PyTorch CPU wheel index, about 15 GB of free disk, and roughly 7 hours of processing on 4 CPUs.

Identifiers will differ from the recorded ones: FRED serves a rolling ten-year window and the GDELT catalog grows daily.

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

Use the first date in the downloaded FRED file as `--start`.

```bash
uv run newsvar calendar build --start 2016-11-25 --end 2025-12-31
```

```bash
uv run newsvar market materialize --calendar-path data/calendars/<calendar_id>.json
```

This prints the market dataset path and the extended calendar path. Both go into `data/study.json` in step 5.

## 3. News titles

```bash
uv run newsvar gdelt catalog
```

The extraction streams about 1.1 TiB and keeps about 1.1 GiB. It commits per day; rerun the same command to resume. `--max-seconds` stops cleanly after a time budget.

```bash
uv run newsvar gdelt extract --start 2019-09-01 --end 2025-12-31 --processes 4 --threads 8
```

```bash
uv run newsvar news corpus --start 2019-09-23 --end 2025-12-31
```

## 4. Sentiment scores

```bash
uv run newsvar news fetch-model
```

Scoring commits every 5,000 titles; rerun to resume. It prints the sampling rate it used.

```bash
uv run newsvar news score --corpus data/derived/news/<corpus_id> --model-snapshot .cache/models/ProsusAI_finbert/5fcfed04a2ca89adf4170ec0a4715103ed7745db
```

## 5. Study configuration

Create `data/study.json`:

```json
{
  "market_dataset": "data/derived/market/<market_dataset_id>",
  "calendar_path": "data/calendars/<extended_calendar_id>.json",
  "corpus": "data/derived/news/<corpus_id>",
  "corpus_start": "2019-09-23",
  "scores_root": "data/derived/scores",
  "model_snapshot": ".cache/models/ProsusAI_finbert/5fcfed04a2ca89adf4170ec0a4715103ed7745db",
  "sampling_rate": 0.27,
  "feature_root": "data/derived/features",
  "study_end": "2025-12-31"
}
```

## 6. Study stages

Run in order. Commit the admission and development records before preregistering; `preregister` refuses to run on a dirty source tree.

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

```bash
uv run newsvar study report --admission-record docs/records/news_admission.json --development-record docs/records/development_record.json --final-record docs/records/final_evaluation.json --ledger data/derived/study/final_forecasts.parquet --output docs/records/result_tables.md
```

A rerun over the same test period replicates this study. It is not a new confirmatory test.

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
