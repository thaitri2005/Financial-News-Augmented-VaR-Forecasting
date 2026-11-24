# Roadmap

What has been done, what the evidence still lacks, and what to do next, in order of value.

## Done

| Step | Outcome |
|---|---|
| Free news source without an account | GDELT titles streamed and verified, 2019-09 to 2026-11 |
| Study 1: FinBERT sentiment in a quantile regression | No improvement; preregistered and reported |
| Diagnosis of study 1 | Too little power, sentiment redundant with VIX, model over-parameterized |
| Volatility-first design with range-based variance | Built; HAR baseline beats historical simulation |
| Supervised text model | Built; development gain of 3–4% in volatility loss |
| Independent review before the test | Two reviews; stale index open found and fixed with SPY prices |
| Study 2: preregistered confirmatory test | Both hypotheses passed on the holdout |
| Operational commands | `newsvar update` and `newsvar forecast` issue and log daily forecasts |

## What the evidence still lacks

1. **A clean, sufficiently long test period.** Only the 224 sessions of 2026 were completely untouched, and there the pooled volatility gain is not significant on its own.
2. **A baseline with intraday prices.** The current baseline sees daily data only.
3. **A curated feed.** GDELT titles are noisy and their timestamps are a proxy.
4. **A human-rated audit** of title relevance and sentiment.

## Next steps

### 1. Log forecasts prospectively (highest value, lowest cost)

Run `newsvar update` and `newsvar forecast` every trading day, once after 15:30 New York time for the pre-close forecast and once after the open for the at-open forecast. Each run appends to `data/forecasts/log.jsonl`.

- Every logged session is clean evidence with real issue times.
- After about 250 sessions, score the log with the same tests. This is the confirmation the present evidence cannot give.
- Needs a machine that keeps `data/` between runs. A cloud session that is reclaimed loses it.

### 2. Add intraday prices to the baseline

Give the pre-close baseline the same-day range up to 15:30 and see whether the text gain survives. On development data an "oracle" baseline with same-day variance and VIX left the volatility gain intact but most of the VaR gain disappeared, so this is the most informative missing control.

- Needs a free intraday source with history. Yahoo serves only about 60 days of 5-minute bars; Alpaca's free plan lists intraday history since 2016 and needs a free account.

### 3. Try a curated headline feed

Alpaca's Benzinga news API is documented back to 2015. Whether it is still free must be checked with an account.

- Real headlines with creation and update times.
- A longer history allows a longer training sample, which is where a learned text model gains most.
- This is a new study with its own preregistration.

### 4. Improve the text model, on development data only

Ideas that were not tried, to avoid tuning on the same data repeatedly:

- a publisher allowlist frozen on training data, to cut off-topic titles;
- separate models for macro, policy and company news;
- refreshing the vocabulary yearly using only past titles;
- a penalty grid chosen by forward-chaining validation instead of contiguous folds.

Each needs a fresh test period; the present holdout is used up for this design.

### 5. Engineering

- A scheduler entry and a small monitor for the two daily commands, with a lock so they cannot overlap.
- An automated end-to-end test of `build_panel` and the study pipeline on synthetic files.
- Faster daily update: rebuild only the newest part of the corpus and term shares instead of everything. `forecast` currently needs about 4 GiB of memory, mostly for the term index, and this grows with the corpus.
- A check that Yahoo's opening price for SPY shortly after 09:30 equals the final official open.
- One shared helper for file hashing and for registration checks, which are duplicated between the two studies.
- The same strict gates for the study 1 commands as for study 2.

## What not to do

- Do not re-tune on 2023-12-14 to 2026-11-20 and call the result a test.
- Do not present the 2–5% volatility gain as a large effect, or as evidence that news beats intraday prices.
- Do not swap in a recent large language model for a historical backtest without handling look-ahead: a model trained on text from the test period can already "know" the outcomes.
