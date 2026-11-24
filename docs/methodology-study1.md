# Methodology of study 1

This describes the study as it was run and evaluated in November 2026. It found no effect. Study 2, which followed, is described in [methodology.md](methodology.md).

## Question

Does news sentiment improve a one-day 95% Value-at-Risk forecast for the S&P 500, beyond what market data and the volume of news already provide?

## Forecast contract

| Element | Definition |
|---|---|
| Target | S&P 500 price-index simple return from the close of session `t` to the close of session `t+1` |
| Forecast | The 5% quantile of that return (95% VaR). The 1% quantile is reported as exploratory |
| Information cutoff | 30 minutes before the scheduled close of session `t`; the forecast is issued 15 minutes before the close |
| Market inputs | Daily closes through session `t-1` only |
| News inputs | Headlines available in `(cutoff of t-1, cutoff of t]` |
| Calendar | NYSE sessions including early closes, from `exchange_calendars` |

Because today's close is not known at the cutoff, the newest usable return is yesterday's. Volatility models therefore forecast two steps ahead and use the second step.

## Data

| Source | Use | Notes |
|---|---|---|
| FRED `SP500` | Target and market features | Daily closes; rolling ten-year history from 2016-11-25 |
| Cboe VIX history | Volatility control | Prior-session close only |
| GDELT GKG 2.0, English feed | News titles | Streamed from the public archive; every 15-minute batch checked against the catalog size and MD5 |

**News selection.** A GDELT record is kept when it is from the web collection, untranslated, tagged with the theme `ECON_STOCKMARKET`, mentions at least one US location, and has a usable page title. Titles are HTML-unescaped, stripped of markup and whitespace-normalized; case, numbers and punctuation are kept.

**Deduplication.** Records are processed in time order. A record is dropped if the same case-folded title or the same URL appeared in the previous 72 hours.

**Availability.** GDELT gives a 15-minute batch time, not a publication time. A title is treated as available at batch time plus 15 minutes. This is a proxy, so results are a historical replay, not issued forecasts.

**Completeness.** A news window is complete when at least 95% of its expected 15-minute batches were retrieved and verified. Incomplete windows are excluded, never read as "no news".

| Corpus, 2019-09-23 to 2025-12-31 | Count |
|---|---:|
| Records with the stock-market theme | 14,146,899 |
| Passing the relevance rule | 6,496,614 |
| Retained after deduplication | 3,794,159 |
| Unique titles | 3,582,698 |
| Titles scored (27% sample) | 967,729 |

## Sentiment

- Model: `ProsusAI/finbert`, pinned to its December 2020 revision, CPU, maximum 128 tokens. Each title gets positive, negative and neutral probabilities.
- The model predates every development and test date, so it cannot have seen them.
- Scoring all 3.58 million titles would take about 14 hours, so a fixed 27% sample was scored. A title is in the sample when the first 32 bits of its SHA-256 fall below 27% of the range. The rule was set before the corpus size was known. News counts always use every retained title.

## Features

Three nested sets, all computed from information available at the cutoff.

| Set | Features |
|---|---|
| **M** market (9) | last return, its absolute value, squared downside; 5-, 21-, 63-day volatility; EWMA volatility; VIX level and change |
| **C** = M + counts (4) | log news rate per 24 hours; its z-score against the previous 63 windows; log window length; has-news flag |
| **S** = C + sentiment (6) | mean signed score; mean negative probability; dispersion; share of negative headlines; mean minus its 21-window average; log negative intensity |

## Models

| Model | Description |
|---|---|
| Q0, Q1, Q2 | Linear quantile regression on M, C, S with an L1 penalty; median imputation and standardization fitted on training rows only |
| T0, T1, T2 | Small gradient-boosted quantile trees on the same sets (secondary) |
| B0 | Historical simulation, last 250 returns |
| B1 | Gaussian EWMA, decay 0.94 |
| B2 | GARCH(1,1) with Student-t innovations, two-step simulation |
| B3 | Filtered historical simulation on the same GARCH filter |

Every model is refitted on the first session of each month, using only rows whose outcome was already known at that moment. Q0, Q1 and Q2 are compared on identical dates.

## Split

The split was fixed from data-availability counts before any return was read.

| Role | Rows | Target dates |
|---|---:|---|
| Training | 691 | 2019-12-24 to 2022-12-12 |
| Development | 250 | 2022-12-13 to 2023-12-13 |
| Final test | 500 | 2023-12-14 to 2025-12-31 |

Development chose one L1 penalty per feature set from {0.001, 0.01, 0.1}, one tree setting from four, and the strongest baseline. Within 0.5% of the best loss, the simpler setting wins.

## Evaluation

- **Score:** pinball (quantile) loss, reported in basis points of return.
- **Primary comparison:** Q2 versus Q1 at the 5% tail. This isolates sentiment from news volume.
- **Uncertainty:** paired moving-block bootstrap of daily loss differences, 2,000 replications, block length 20, fixed seed; blocks of 10 and 5 as checks.
- **Decision rule:** the claim is supported only if the mean improvement is positive and the 95% interval excludes zero. A 2% relative gain marks practical interest.
- **Calibration:** breach counts, Kupiec coverage test, Christoffersen independence test, longest breach run.
- **Sensitivities (features rebuilt, models refitted):** availability delays of 60 and 240 minutes and one full session; sentiment lagged 5 and 20 days; market-recap headlines removed; the largest publisher removed; counts including duplicates.

## Preregistration

Inputs, split, features, chosen settings, the primary comparison and the decision rule were written to [a preregistration record](records/preregistration_20261124.json) and committed before the test period was evaluated. The test was evaluated once.

## Limits to keep in mind

1. **Noisy source.** GDELT page titles are not curated financial headlines. In a 200-title audit, 14–16% were off-topic (crime, local politics, product pages). The audit was rated by the implementing agent, not a human annotator.
2. **Archive gaps.** GDELT lacks batches in late 2020, mid 2021 and June 2025. 2020 has 84.2% complete windows against a planned minimum of 90%. Overall completeness is 95.4%.
3. **Small sample.** 500 test forecasts mean 25 expected breaches at 5%. Only large effects are detectable.
4. **Sampled sentiment.** The 27% sample adds noise to daily sentiment (standard error about 0.022 against a day-to-day spread of 0.060).
5. **One development year**, and a calm one.
6. **Proxy timing**, as described above.
