# News study contract: GDELT stream, corpus, scores, features and staged evaluation

This contract covers the modules added on 2026-11-24 for M0-04, M1-05–M1-08, M3-01–M3-04, M4-02–M4-05 and M5. The blueprint owns the scientific rules; this file states what each module guarantees and what it does not.

## Stages and artifacts

| Stage | Command | Module | Private artifact (Git-ignored) | Reads returns? |
|---|---|---|---|---|
| Extract | `newsvar gdelt extract` | `ingestion/gdelt.py` | `data/raw/gdelt/titles/date=YYYY-MM-DD/{titles.parquet,manifest.json}` | no |
| Corpus | `newsvar news corpus` | `news.py` | `data/derived/news/<corpus_id>/{events,titles,batches}.parquet` | no |
| Score | `newsvar news score` | `scoring.py`, `sentiment.py` | `data/derived/scores/<fingerprint_id>/part-*.parquet` | no |
| Admit | `newsvar study admit` | `study.py`, `feature_table.py` | `data/derived/features/<table_id>/` | no |
| Develop | `newsvar study develop` | `study.py`, `experiments.py` | — | development range only |
| Preregister | `newsvar study preregister` | `study.py` | — | no |
| Evaluate | `newsvar study evaluate` | `study.py` | `data/derived/study/final_forecasts.parquet` | test range, once |
| Report | `newsvar study report` | `report.py` | — | reads the ledger; fits nothing |

Study commands read their input paths from `data/study.json` (`market_dataset`, `calendar_path`, `corpus`, `corpus_start`, `scores_root`, `model_snapshot`, `sampling_rate`, `feature_root`, `study_end`).

## Extraction (`gdelt_gkg_stream_v1`)

- Input: the saved master catalog. Each English GKG batch has a catalogued byte count and MD5.
- Per batch: download, check size and MD5 against the catalog, decompress one bounded member, keep rows whose V1 themes contain the whole code `ECON_STOCKMARKET`, discard the payload.
- Per UTC day: one atomically committed directory with the matched rows and a 96-entry ledger. Each entry is `ok`, `absent_from_catalog`, `fetch_failed`, `size_mismatch`, `md5_mismatch` or `bad_archive`.
- A day is final when every catalogued batch is `ok`. A non-final day is retried on the next run; a final day is never refetched.
- Not guaranteed: raw payload retention; publisher publication time; completeness of GDELT's own crawl. A batch absent from the catalog is a real feed gap, not an empty interval.

## Corpus (`news_corpus_v2`)

- Relevance `gdelt_en_web_us_stockmarket_title_v1`: web collection, untranslated, at least one US location, title of at least 10 characters containing a letter. Excluded rows are counted by cause.
- Normalization `headline_text_v1`: HTML-unescape (twice, because the archive double-escapes), strip markup, NFC, collapse whitespace. Case, digits, punctuation and negations are preserved.
- Dedup `exact_casefold_title_or_url_72h_v1`: records are processed in batch order; a record is a duplicate if the same case-folded title or the same URL occurred within the previous 72 hours. Every occurrence refreshes the lookback. Only past records are consulted, so appending later days cannot change an earlier status.
- `sample_key` is the first 32 bits of the title's SHA-256. It defines the frozen probability sample for scoring.

## Availability and windows

- Class B proxy: `available_at = batch time + buffer` (15 minutes by default).
- Window of origin `t`: `(cutoff[t-1], cutoff[t]]` on the frozen XNYS calendar. An item available exactly at the cutoff is included; one second later belongs to the next origin.
- `feed_complete`: at least 95% of the window's expected 15-minute batches are `ok`.
- A complete window with no retained headline has `has_news = 0` and null sentiment. An incomplete window has null news features and is ineligible.

## Scores

- Encoder: `ProsusAI/finbert` at revision `5fcfed04a2ca89adf4170ec0a4715103ed7745db`, CPU FP32, maximum length 128, loaded from local files only. The label map is asserted.
- Scores are keyed by content hash and model fingerprint and committed in parts of 5,000 titles; an interrupted run resumes without rescoring.
- If the corpus has more than 1,000,000 unique retained titles, only titles with `sample_key` below the threshold for rate `floor(1e6 / unique, 2 decimals)` are scored. Counts use the full retained feed. Sentiment means use the scored sample. `negative_log_intensity` divides the summed negative probability by the rate. Scoring coverage is measured against the designated sample.

## Feature table

- One row per origin with the 19 blueprint features and quality fields.
- Market features use labels and VIX values whose recorded availability is at or before the cutoff, and require the newest known return to be session `t-1`.
- A row is eligible when: market history is present and not stale; the 63 preceding windows all lie inside the corpus; the window is feed-complete; scoring coverage is at least 98%.
- Q0, Q1 and Q2 share this single eligibility mask.
- Declared variants (`FeatureConfig`): availability buffer, one-session delay, sentiment lag, recap exclusion, dominant-source exclusion, counts including duplicates. Each variant is a separate table with its own identifier. `counts_include_duplicates` changes counts only; sentiment still comes from retained headlines.

## Experiments

- Refit on the first origin of each calendar month. Training rows are eligible rows with an earlier origin whose label was available at that refit cutoff. Fewer than 250 training rows is a visible failure, not a forecast.
- Linear models: `fit_linear_quantile` with penalties 0.001, 0.01, 0.1. Tree challenger: depth 1–2, 100–200 trees, leaf size 50, learning rate 0.05, seed 1729.
- Selection: lowest development mean pinball loss; candidates within 0.5% of the best resolve to the more regularized (linear) or smaller (tree) setting.
- Baselines B0–B3 are produced by the existing M2 code for the same target range and compared on the eligible grid.

## Split rule

Applied to outcome-blind eligibility counts by `study.decide_split`:

1. If at least 500 usable rows have a target end on or before 2021-12-31: the blueprint's GDELT alternative (development 2022, test 2023–2025).
2. Otherwise, with at least 1,250 usable rows: the reduced-study rule — last 500 usable rows are the test, the preceding 250 are development, and at least 500 earlier rows are training.
3. Otherwise: prototype only; `develop` refuses to run.

## Gates enforced in code

- `study preregister` refuses to run with uncommitted changes under `src`, `pyproject.toml` or `uv.lock`, and records the commit and lockfile hash.
- `study evaluate` refuses to run if the preregistration identifier does not match its content, if the inputs or feature table differ from the registered ones, or if a final record already exists.
- `study develop` computes nothing outside the development range.

## Verification

Synthetic fixtures only; no test touches the network or real outcomes: `tests/test_gdelt_stream.py`, `tests/test_news.py`, `tests/test_feature_table.py`, `tests/test_experiments.py`, plus additions to `tests/test_features.py` and `tests/test_metrics.py`. A fully synthetic rehearsal of admit → develop → preregister → evaluate → report was run before any real outcome was read.

## Limitations

- GDELT page titles are not vendor headlines. They include boilerplate from stock-note sites and unrelated pages that mention a market term.
- The availability time is an archive batch proxy. Results are historical-proxy results, not issued forecasts.
- The pipeline has no integration test in the ordinary suite; the rehearsal is a script run, recorded in the review, not an automated check.
