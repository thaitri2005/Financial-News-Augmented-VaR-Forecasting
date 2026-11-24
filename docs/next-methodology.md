# A stronger methodology for the next study

The first study found no benefit from news sentiment. This document asks why the design had little chance of finding one, what the literature does differently, and what to build next. It ends with a concrete, ordered plan.

**Recommendation in one paragraph.** Stop testing news directly on the 5% quantile with a 19-feature regression. Test it on **volatility** first, where the target is continuous and the statistics are far more powerful; turn the news-augmented volatility into VaR and expected shortfall through a filtered-historical-simulation step; feed the model a **news surprise** (tone not already explained by VIX) from a **curated, timestamped feed**; and judge it with joint VaR/ES scores and conditional tests on a **fresh or prospective** test period.

## 1. Why the first design was weak

Each point below is measured on our own data. Items marked *training + development* use only rows with target dates up to 2023-12-13, so the spent test period plays no part in shaping the proposal. The script is [`scripts/diagnose_news_signal.py`](../scripts/diagnose_news_signal.py). These numbers are exploratory.

| Weakness | Evidence |
|---|---|
| **The target has almost no statistical power.** | A 5% quantile produces 25 breaches in 500 days. On the test, the interval for "quantile regression vs GARCH-t" spans about ±6.7% of the loss. Detecting a 2% gain between two distinct models at that noise level would need roughly 5,000 trading days. |
| **Sentiment mostly restates the market.** | *Training + development:* mean negative probability correlates +0.59 with yesterday's VIX and −0.33 with yesterday's return. The model already has both. |
| **A small signal does exist, in volatility.** | *Training + development:* after controlling for VIX, 21-day volatility, EWMA volatility and yesterday's absolute return, the share of negative headlines still predicts next-day log absolute return (HAC t = 2.9; R² 0.171 → 0.179). News counts add nothing (t = 0.4). |
| **The model was over-parameterized.** | *Development:* "5% quantile = constant × VIX", one parameter, scores 8.72 bp. Our 9-feature market regression scores 8.76 bp and GARCH-t 8.85 bp. Nineteen features on 700 rows forces a heavy penalty that zeroes out anything subtle. |
| **Training and test regimes differ.** | Training is 2020–2022 (pandemic, rate shock). The models were too conservative in 2023: 5 breaches against 12.5 expected. |
| **The source is noisy.** | 14–16% of audited titles were off-topic. Selection is by a GDELT theme tag, not by publisher or desk. |
| **Sampling was a minor issue.** | *Training + development:* the 27% sample gives a standard error of 0.022 on daily mean sentiment against a day-to-day spread of 0.060. It costs some precision but is not the main problem. |
| **Missing same-day price is not the gap.** | *Training + development:* adding the same-day absolute return (unknown at the cutoff, used here only as a diagnostic) does not help predict the next day (t = −1.0). |

The picture is consistent: there is a faint, real-looking volatility signal in negative tone, and the first design was the wrong instrument to detect it.

## 2. What the literature does

| Idea | Source | Relevance |
|---|---|---|
| News enters the **volatility** equation, not the quantile | Bernardi, Catania & Petrella, "Are news important to predict large losses?" ([arXiv 1410.6898](https://arxiv.org/pdf/1410.6898), European Journal of Finance 2017) | Sentiment indices as exogenous terms in GARCH-type models; VaR compared with the Model Confidence Set |
| Realized measures plus sentiment for VaR and ES | Naimoli, "The information content of sentiment indices for forecasting VaR and ES" ([MPRA 117221](https://mpra.ub.uni-muenchen.de/117221/16/VaR_ES_EPU.pdf)) | Realized EGARCH with sentiment and policy-uncertainty terms on the S&P 500; reports tail-risk gains. A working paper |
| HAR volatility models extended with news | Bodilsen & Lunde (2025), cited in a Federal Reserve working paper ([FEDS 2025-061](https://www.federalreserve.gov/econres/feds/files/2025061pap.pdf)) | Macro and firm news sentiment added to HAR through a MIDAS weighting |
| Learn what news implies about volatility directly | Manela & Moreira, "News implied volatility and disaster concerns" ([JFE 2017](https://ideas.repec.org/a/eee/jfinec/v123y2017i1p137-162.html)) | A text regression maps newspaper words to VIX; the fitted value (NVIX) predicts VIX out of sample. Topic matters: war and policy news carry the priced risk |
| Quantile dynamics with few parameters | Engle & Manganelli, CAViaR (JBES 2004) | The quantile follows its own lag plus a function of the last return: 3–4 parameters, and room for one exogenous term |
| Joint VaR and ES estimation and scoring | Taylor ([JBES 2019](https://ideas.repec.org/a/taf/jnlbes/v37y2019i1p121-133.html)); Patton, Ziegel & Chen, "Dynamic semiparametric models for expected shortfall" ([working paper](https://bundesbank.de/resource/blob/636452/bc93f367795a81ccad0353ad4177a0df/472B63F073F071307366337C94F8C870/2017-09-08-frankfurt-03-1-paper-data.pdf)); Fissler & Ziegel (2016) | The FZ0 loss scores a VaR and ES pair consistently. It uses the size of losses beyond VaR, so it is more informative than counting breaches |
| Ask *when* one forecast is better | Giacomini & White, "Tests of conditional predictive ability" ([Econometrica 2006](https://econometricsociety.org/publications/econometrica/2006/11/01/tests-conditional-predictive-ability)) | Tests whether news helps in identifiable states, such as high VIX or heavy news days, instead of only on average |
| Compare many models without cherry-picking | Hansen, Lunde & Nason, Model Confidence Set (Econometrica 2011) | Returns the set of models not distinguishable from the best |
| Language-model look-ahead | Glasserman & Lin ([arXiv 2309.17322](https://arxiv.org/pdf/2309.17322)) | A model trained on text from the test period can "know" outcomes. Use an encoder whose training predates the test, as the 2020 FinBERT does, or test only after the model's cutoff |

The classic papers without links (CAViaR, the Model Confidence Set, Fissler–Ziegel) are cited from memory; check details before quoting them. Several linked items are working papers.

## 3. The proposed design

### 3.1 Two stages: volatility first, then VaR

**Stage A — does news improve a volatility forecast?**

- Target: next-session variance, measured by a realized or range-based proxy rather than the squared close-to-close return.
- Baseline: HAR (daily, weekly, monthly volatility averages) plus VIX.
- Challenger: the same model plus one or two news terms.
- Score: QLIKE loss, which is robust to noise in the volatility proxy.

A continuous target observed every day is far more informative than 25 breaches. If news cannot improve the volatility forecast, it will not improve VaR, and the project can stop early with a clear answer.

**Stage B — does that carry through to VaR and ES?**

- VaR = forecast volatility × an empirical quantile of past standardized returns (filtered historical simulation). ES comes from the same residuals.
- The news effect enters only through volatility, so Stage B adds no new news parameters.
- Compare baseline-volatility VaR with news-volatility VaR.

This needs a better volatility proxy than FRED closes. Options, cheapest first:

1. Daily open-high-low-close for the index or SPY, giving Parkinson or Garman–Klass range estimators.
2. Free intraday bars (Alpaca's free plan lists history since 2016) to build 5-minute realized variance.
3. An open realized-measure archive such as VOLARE ([arXiv 2602.19732](https://arxiv.org/abs/2602.19732)), which covers the E-mini S&P 500 future.

The first study excluded SPY and intraday data to keep the target pure. That rule can stay for the *target* (index close-to-close return) while a range or realized measure is used only as a *feature and scoring proxy*.

### 3.2 A parsimonious quantile model as a cross-check

Keep one direct quantile model, but small:

```text
q_t = sigma_t × (a + b × news_surprise_t)
```

`sigma_t` is VIX or the Stage A forecast. Two parameters instead of nineteen. A CAViaR recursion with one news term is the natural alternative. If `b` is not distinguishable from zero here either, the negative result is much more convincing than the first one.

### 3.3 News surprise instead of news level

Tone is 0.59 correlated with VIX. Feed the model what is new:

- Regress the tone measure on VIX, recent returns and its own lags, on an expanding window; use the residual.
- Keep it to one or two series: the negative-headline share (the strongest in the diagnostic) and, if a curated feed allows, a topic-specific variant.
- Drop news counts unless a new diagnostic revives them.

### 3.4 A better source and better text features

| Change | Why |
|---|---|
| **Curated, timestamped feed.** First choice: Alpaca's Benzinga news API, documented with history back to 2015. Whether it is still free must be checked with a real account; the 2022 launch described free access as a beta ([Alpaca launch post](https://alpaca.markets/blog/introducing-news-api-for-real-time-fiancial-news), [docs](https://docs.alpaca.markets/us/docs/historical-news-data)) | Real headlines with creation and update times; removes most off-topic noise; allows a 2017–2025 split with about 2,000 rows |
| **If GDELT stays:** select by a publisher allowlist frozen on training data, not by theme tag alone | The extraction already stores the publisher for every title |
| **Topics, not one polarity.** Separate macro and policy, earnings, and geopolitical headlines | Manela & Moreira find that the type of news matters |
| **A supervised text-to-volatility index.** On training data only, fit a penalized regression from title text to next-day volatility or VIX change; use its out-of-sample prediction as the single news feature | This is the NVIX idea. It lets the data choose which words matter instead of assuming generic sentiment does |
| **Score every title** | Removes sampling noise; 14 hours of CPU, once |
| **Split overnight and intraday news** | Overnight news is not yet in yesterday's close; intraday news partly is |

### 3.5 More statistical power

In order of value:

1. **Longer history** with a feed that reaches 2015–2017.
2. **A panel of assets.** Sector ETFs or large caps with ticker-tagged news, estimated with pooled coefficients and errors clustered by date. Ten assets do not give ten times the information, because they move together, but they help.
3. **Report expected shortfall.** The FZ0 loss uses the magnitude of tail losses.
4. **A power calculation before preregistration.** Simulate the planned test with a plausible effect size and state the smallest effect it can detect. The first study skipped this.

### 3.6 Evaluation

| Element | First study | Proposed |
|---|---|---|
| Primary target | 5% quantile pinball loss | Stage A: QLIKE on volatility. Stage B: FZ0 on VaR and ES |
| Average comparison | Paired block bootstrap | Keep, and add a Diebold–Mariano test with HAC errors |
| State dependence | Three volatility buckets, descriptive | Giacomini–White conditional test with predeclared instruments: lagged VIX and a heavy-news indicator |
| Many models | Pairwise table | Model Confidence Set |
| Calibration | Kupiec, Christoffersen | Keep, and add the dynamic quantile test |
| Preregistration | Yes | Keep, with the power calculation included |

### 3.7 Test period

The 2023-12-14 to 2025-12-31 window is used up for this question. Choices:

- **Prospective.** Start logging GDELT batches and forecasts now. This also upgrades timing from a proxy to actually observed arrival times. Slow: a year gives about 250 days.
- **A different feed with a longer history**, treated as a new study with its own split. The 2024–2025 period would then be a replication on new data, reported as such.
- **Cross-asset replication** on assets not examined so far.

The honest position is that no retrospective test on 2024–2025 can be fully confirmatory again.

## 4. Plan

| Step | Work | Needs | Effort |
|---|---|---|---|
| 1 | Add a range-based or realized volatility proxy; build HAR + VIX baseline and QLIKE scoring | A free OHLC or intraday source | Small |
| 2 | Stage A on existing GDELT features, development period only: negative-share surprise added to HAR | Nothing new | Small; a quick go/no-go |
| 3 | Power calculation by simulation | Nothing new | Small |
| 4 | Curated feed pilot: confirm free access, history and timestamps on one week per year | A free Alpaca account key from the project owner | Small, then a backfill of a few hours |
| 5 | Text features: publisher allowlist or curated feed, topic split, supervised text-to-volatility index; score all titles | Step 4 or the existing corpus | Medium |
| 6 | Stage B: filtered historical simulation VaR and ES; FZ0, conditional tests, Model Confidence Set | Steps 1–5 | Medium |
| 7 | Preregister and evaluate on the chosen fresh period; start a prospective log in parallel | Steps 1–6 | Small, plus waiting time |

Step 2 is the cheapest decisive experiment. If a news surprise does not lower QLIKE against HAR + VIX on development data, the remaining steps are unlikely to change the conclusion, and that is worth knowing before investing in a new feed.

## 5. What not to do

- Do not re-tune the first design on 2024–2025 and call the result a test.
- Do not add more sentiment aggregates to the 19-feature regression. The problem is too many parameters, not too few.
- Do not replace FinBERT with a recent large language model for a historical backtest without handling look-ahead.
- Do not treat the small volatility signal in section 1 as a finding. It is in-sample and exploratory; it justifies the next experiment, nothing more.
