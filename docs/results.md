# Results

Two preregistered studies asked whether financial news improves next-day risk forecasts for the S&P 500.

| | Study 1 | Study 2 |
|---|---|---|
| News signal | FinBERT sentiment averages | Ridge model of headline terms |
| Model | 19-feature quantile regression | HAR volatility model, then VaR and ES |
| Test | 500 sessions, Dec 2023 – Dec 2025 | 722 sessions, Dec 2023 – Nov 2026 |
| Primary result | −0.06% change in 5% quantile loss | Pooled volatility loss lower, one-sided p = 0.003 |
| Registered verdict | Not supported | **Strong** (both hypotheses pass) |

**Bottom line.** News helps a little when the model learns which headline words matter and the target is volatility. Generic sentiment does not help. The gain is small: 2–5% in volatility loss and about 1.5% in VaR loss.

The full write-up is the [PDF report](../report/report.pdf). Study 1 is detailed in [results-study1.md](results-study1.md). Method: [methodology.md](methodology.md).

## Study 2: primary test

Holdout: 2023-12-14 to 2026-11-20. The text model is compared with the HAR baseline; the test averages the two forecast set-ups' daily improvements.

| Hypothesis | Loss | Sessions | t | One-sided p | Passed |
|---|---|---:|---:|---:|---|
| H1 (primary) | QLIKE, volatility | 722 | 2.75 | 0.003 | yes |
| H2 (key secondary) | FZ0, 5% VaR and ES jointly | 722 | 1.72 | 0.043 | yes |
| supporting | Pinball, 5% VaR | 722 | 2.55 | 0.005 | |

Each set-up also passes alone after Holm correction (p = 0.010 pre-close, 0.045 at-open).

![Cumulative volatility-forecast gain of the text model](figures/vol_cumulative_qlike.png)

## By forecast set-up

| | Pre-close (722 sessions) | | At-open (724 sessions) | |
|---|---:|---:|---:|---:|
| | Baseline | Text model | Baseline | Text model |
| QLIKE | 0.4180 | 0.3978 | 0.3274 | 0.3198 |
| 5% pinball loss (bp) | 11.39 | 11.22 | 9.00 | 8.89 |
| 5% breaches (36 expected) | 27 | 30 | 34 | 33 |
| 1% breaches (7.2 expected) | 8 | 8 | 7 | 8 |
| Coverage test p, 5% | 0.10 | 0.28 | 0.70 | 0.58 |
| **QLIKE gain from text** | | **+4.8%** (t = 2.58) | | **+2.3%** (t = 1.69) |
| **5% pinball gain from text** | | **+1.5%** (t = 1.98) | | **+1.3%** (t = 2.46) |

For scale, the baseline alone beats 250-day historical simulation by 4.7% (pre-close) and 9.9% (at-open) in 5% pinball loss, and historical simulation has 15 breaches at the 1% level against 7.2 expected. Most of the accuracy comes from the volatility model; news adds a small step.

## The never-evaluated 2026 slice

The 224 sessions of 2026 had never been evaluated in any form before this test.

| 2026 only | Pre-close | At-open | Pooled |
|---|---:|---:|---:|
| QLIKE gain from text | +4.3% (t = 1.72) | −1.7% (t = −0.58) | t = 0.55, p = 0.29 |
| 5% pinball gain from text | +1.8% (t = 1.15) | +1.6% (t = 2.01) | t = 1.68, p = 0.047 |

This is the cleanest evidence and it is mixed: the pre-close volatility gain holds, the at-open one does not, and the VaR-loss gain holds in both. With 224 sessions the slice neither contradicts nor independently confirms the main result.

## Which news signal matters

![QLIKE improvement by news term](figures/vol_gains_by_term.png)

| News term added to the baseline | Pre-close QLIKE gain | At-open QLIKE gain | Status |
|---|---:|---:|---|
| Text model | +4.8% | +2.3% | registered hypothesis |
| News-count surprise | +1.9% (t = 2.08) | +1.9% (t = 2.62) | exploratory |
| FinBERT negative share | +2.6% (t = 1.06) | +0.5% | exploratory |
| FinBERT negative-share surprise | +1.9% (t = 0.92) | −0.2% | exploratory |
| FinBERT mean-negative surprise | +2.0% (t = 0.98) | −0.2% | exploratory |

![Largest term weights](figures/vol_term_weights.png)

Many of the largest weights are sensible ("ahead fed", "sell-off", "futures drop" raise the forecast; "stocks rally", "hit record" lower it). Others are noise from an unfiltered web feed.

## Robustness (run after the evaluation; descriptive)

- **Not one episode.** Without April 2025, the pooled QLIKE test still gives t = 2.67.
- **Concentrated, as QLIKE gains usually are.** The best 1% of days supply 53% of the total gain. Removing the best and worst 1% gives t = 4.27.
- **State-dependent.** The conditional predictive ability test rejects equal accuracy in both set-ups (p = 0.004 and 0.028).
- **Not just that day's market move.** On development data, giving the pre-close baseline the same-day variance and VIX (which it cannot have in practice) left the volatility gain at +3.4% (t = 3.3); the VaR gain shrank from +2.2% to +0.6%.

![Pre-close VaR and ES forecasts](figures/vol_var_forecasts.png)

## Limits

1. **Small effect.** Statistically supported, not large.
2. **Part of the holdout was used before.** December 2023 to December 2025 was study 1's test period, and study 1's failure prompted this design. No volatility or text model had been evaluated there, but the design is not blind to that period.
3. **Daily-data baseline.** The result shows news text improves a model built from daily prices. It does not show that news beats intraday prices, which were not available.
4. **Noisy source.** GDELT page titles, about one in seven off-topic in an audit rated by the project's AI agent, not a human.
5. **Proxy timestamps.** News is dated by GDELT's 15-minute batch plus 15 minutes.
6. **Development choices.** Five news terms, two penalty grids, two feature forms and two price sources were compared on development data. All are in the [research log](research-log.md). The penalty grid changes the pre-close development result noticeably.
7. **The 1% tail** is not improved by news.

## Records

| Record | Content |
|---|---|
| [volatility_preregistration](records/volatility_preregistration_20261124.json) | Frozen protocol, hypotheses, disclosures |
| [volatility_evaluation](records/volatility_evaluation_3f5a032a19e2.json) | Holdout results |
| [volatility_summary](records/volatility_summary_3f5a032a19e2.json) | Slice tests and term weights |
| [volatility_result_tables](records/volatility_result_tables.md) | All tables, generated |
| [volatility_development](records/volatility_development_20261124.json) | Development-period results |
| Study 1 records | Listed in [results-study1.md](results-study1.md) |
