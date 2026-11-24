# Architecture

`newsvar` is a small batch pipeline. Each stage reads committed artifacts from the previous stage, writes its own artifact atomically, and can be rerun or resumed. There is no service, database server or scheduler.

## Pipeline

```mermaid
flowchart LR
    A[FRED closes, Cboe VIX<br/>index and SPY bars] --> B[Returns and<br/>range variance]
    C[XNYS calendar] --> B
    D[GDELT archive] --> E[Title store<br/>per UTC day]
    E --> F[News corpus<br/>events, titles]
    F --> T[Term shares<br/>per news window]
    F --> G[FinBERT scores<br/>secondary]
    B --> H[HAR baseline]
    T --> R[Text ridge on<br/>HAR residual]
    H --> V[VaR and ES by<br/>filtered simulation]
    R --> V
    G -.-> H
    V --> S[Study: develop,<br/>preregister, evaluate]
    V --> O[Operations:<br/>update, forecast]
```

The same forecasting code serves the study and daily operation.

| Stage | Command | Writes (private, Git-ignored) |
|---|---|---|
| Market snapshot | `newsvar market fetch` | `data/raw/market/` |
| Calendar | `newsvar calendar build` | `data/calendars/<id>.json` |
| Market dataset | `newsvar market materialize` | `data/derived/market/<id>/` |
| GDELT catalog | `newsvar gdelt catalog` | `data/raw/gdelt/masterfilelist.txt` |
| Title extraction | `newsvar gdelt extract` | `data/raw/gdelt/titles/date=YYYY-MM-DD/` |
| Corpus | `newsvar news corpus` | `data/derived/news/<id>/` |
| Model files | `newsvar news fetch-model` | `.cache/models/ProsusAI_finbert/<revision>/` |
| Scoring | `newsvar news score` | `data/derived/scores/<fingerprint>/` |
| Bars | `newsvar market fetch-ohlc` | `data/raw/market/yahoo_*.json` |
| Volatility study | `newsvar vol develop / preregister / evaluate / report` | `data/derived/text_shares/`, `data/derived/study/` |
| Study 1 | `newsvar study admit / develop / preregister / evaluate / report` | `data/derived/features/<id>/`, `data/derived/study/` |
| Operations | `newsvar update`, `newsvar forecast` | `data/operations.json`, `data/forecasts/log.jsonl` |

Public, committed outputs are the JSON records in [records/](records/) and the figures in [figures/](figures/). They contain counts, hashes and aggregate scores only.

## Package layout

| Package | Modules | Responsibility |
|---|---|---|
| `newsvar.data` | `calendar`, `market`, `labels`, `datasets`, `ohlc` | Exchange calendar and forecast origins; price sources; return labels; versioned market tables; daily bars |
| | `gdelt`, `news` | Streaming title extraction; normalization, relevance, deduplication, window assignment |
| `newsvar.nlp` | `encoder`, `scoring` | Pinned FinBERT loading; resumable bulk scoring |
| `newsvar.features` | `intervals`, `text_index` | News tone over any time interval and its surprise; headline term shares with a frozen vocabulary |
| | `definitions`, `table` | Study 1: the 19 feature formulas and the per-origin feature table |
| `newsvar.volatility` | `proxies`, `har`, `text_ridge`, `tail` | Range-based variance; log-HAR regression; ridge on HAR residuals with stacking; volatility-scaled VaR and ES |
| `newsvar.models` | `baselines`, `garch`, `quantile` | Study 1: historical simulation, EWMA, GARCH-t, penalized quantile regression |
| `newsvar.evaluation` | `metrics`, `inference` | Pinball loss, coverage tests, block bootstrap; QLIKE, FZ0, Diebold–Mariano, Giacomini–White, dynamic quantile |
| | `walkforward`, `experiments` | Study 1 walk-forward runners |
| `newsvar.study` | `volatility`, `volatility_report`, `operate` | Study 2 panel, forecasts, registration and evaluation; its tables and figures; operational forecasts |
| | `pipeline`, `report` | Study 1 stages and report |
| `newsvar` | `cli`, `doctor`, `hashing` | Command line; resource preflight; canonical JSON and SHA-256 |

Dependencies point one way: `study` → `evaluation` → `models`, `features` → `data`, `nlp`. Heavy libraries (PyTorch, scikit-learn, arch, matplotlib) are imported inside the functions that need them, so light commands start fast.

## Design rules

**Time is explicit.** Every forecast origin carries its cutoff (30 minutes before the scheduled close), issue deadline and target interval, built once from the exchange calendar. A news item belongs to the window `(previous cutoff, cutoff]` by its availability time. A market value or label is usable only if its recorded availability is at or before the cutoff. Tests cover the boundaries and check that changing future data cannot change an earlier row.

**Missing is not zero.** A GDELT batch that is absent or failed verification makes its window incomplete. Incomplete windows are excluded; they are never treated as "no news".

**Artifacts are content-addressed.** A dataset's directory name is the SHA-256 of its declared identity (inputs, rules, versions). Tables carry checksums that are verified on load. A changed rule produces a new directory instead of overwriting an old one.

**Writes are atomic and resumable.** Stages write to a staging path and rename. Extraction commits per day and scoring per 5,000 titles, so an interrupted run continues where it stopped.

**Gates are enforced in code.**
- `vol develop` drops every row after the development end before fitting.
- `vol preregister` refuses to run with uncommitted source changes. It records inputs by hash, source by content, every protocol constant and the eligible holdout row counts.
- `vol evaluate` requires the registration to be committed, compares every recorded value with the code and data, writes an "opened" marker before computing any outcome, and refuses a second run.
- The study 1 commands have equivalent gates.

**One code path for study and operation.** `forecast_all` produces every forecast. In study mode it forecasts only sessions with known outcomes so all models share one sample. In operations it also forecasts a session whose outcome is unknown, and an `as_of` time ensures that an unfinished session contributes no outcome.

**Raw text stays private.** Titles, prices and per-date forecasts live under `data/`. Nothing there is committed.

## Resource profile

Built for CPU and at most 8 GB of memory. `newsvar doctor --stage sentiment` checks the machine before heavy stages (5 GiB free RAM for scoring, 3 GiB for normalization, 15 GiB free disk).

| Stage | Measured on 4 CPUs, 15 GiB RAM |
|---|---|
| GDELT extraction, 2,641 days | about 3 h 15 min; 1.3 TiB streamed, 1.2 GiB kept |
| Corpus build | 4.5 min |
| FinBERT scoring, 1.15 million titles | about 5 h (not needed by the text model) |
| Term shares for 2,500 windows | 3 min |
| Development run, registration, holdout evaluation | about 3, 3 and 6 min |
| Daily `update` + `forecast` | about 5 + 5 min |

## Operations

```bash
uv run newsvar update
```

```bash
uv run newsvar forecast
```

`update` refreshes prices, bars, the calendar, GDELT titles (re-extracting the last three days, because a day extracted before it ended is incomplete), the corpus and scores. `forecast` issues volatility, 95% and 99% VaR and ES for the next session in each set-up that has reached its information time, for the baseline and the text model, and appends the record to `data/forecasts/log.jsonl`. Earlier log entries are never rewritten, so the log is a prospective record with real issue times.

## Not built

- A scheduler: run the two commands from cron or a task scheduler.
- Continuous memory monitoring.
- Intraday prices in the baseline.

## Tests

`tests/` holds synthetic fixtures only: no network, no real prices, no real news. They cover calendar boundaries, label adjacency, baseline arithmetic, GARCH two-step simulation, batch verification and resume, deduplication causality, window assignment, feature eligibility, walk-forward chronology, coverage tests, the bootstrap, range variance, the HAR fit, the loss functions and tests, the text model's stacking rule, registration checks, and perturbation tests showing that outcomes and text dated after a forecast's information time cannot change it.
