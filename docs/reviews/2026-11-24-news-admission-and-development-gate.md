# 2026-11-24 — News-source admission, sentiment audit and development-experiment gate

**Scope:** M0-04, M0-06, M1-05–M1-08, M3-01–M3-04 exit; gate before M4 development experiments. **Reviewer role:** implementing agent (self-review, not independent). **Outcome:** GDELT titles admitted for a **qualified, reduced-power historical-proxy study**; development experiments approved. No return had been read when these decisions were recorded.

Evidence: [extraction ledger](../research/gdelt_extraction_20261124.json), [corpus manifest](../research/news_corpus_20261124.json), [admission record](../research/news_admission_20261124.json), [module contract](../development/m1_m5_news_study_contract.md), [ingestion gate](2026-11-24-gdelt-stream-ingestion-gate.md).

## What was extracted

| Item | Value |
|---|---|
| UTC days | 2,314 (2019-09-01 – 2025-12-31) |
| Compressed bytes streamed and verified | 1,240,159,688,565 (1.128 TiB) |
| Batches verified against catalog size and MD5 | 216,999 |
| Batches absent from the catalog | 5,054 |
| Catalogued batches returning HTTP 404 | 91 (2020-12-14, 2022-11-10/11, 2023-03-23) |
| GKG rows read | 304,932,742 (301,084,249 with a title) |
| Rows with `ECON_STOCKMARKET` | 14,312,034 |
| Wall time | about 2 h 50 min on 4 CPUs; about 1.1 GiB retained |

`PAGE_TITLE` first appears on 2019-09-22, so the corpus starts 2019-09-23.

## Corpus (`d2287582…ebbe5`, 2019-09-23 – 2025-12-31)

| Stage | Rows |
|---|---:|
| Matched rows in range | 14,146,899 |
| Excluded: no US location | 7,640,039 |
| Excluded: no title | 7,730 |
| Excluded: title too short or non-alphabetic | 2,516 |
| Relevant events | 6,496,614 |
| Suppressed: duplicate title within 72 h | 2,702,423 |
| Suppressed: duplicate URL within 72 h | 32 |
| Retained events | 3,794,159 |
| Unique retained titles | 3,582,698 |

## Admission criteria (blueprint §6.2)

| Requirement | Result | Verdict |
|---|---|---|
| Use rights | GDELT open-access terms; titles and derived tables stay private; only counts and hashes are committed | pass |
| Completeness of retrieval | every catalogued batch verified or recorded as failed; no result cap exists in this route | pass |
| Timestamps | 100% of events carry a 15-minute batch time in UTC; Class B proxy | pass (proxy) |
| Text version | the title preserved in the batch; never refreshed from the live URL | pass |
| Manual audit of at least 100 records | 200-headline agent-rated audit below; no timezone field exists to mis-shift | pass with limitation |
| Windows complete overall, at least 95% | 1,504 / 1,576 = 95.43% | pass |
| Windows complete in each year, at least 90% | 2019 100%, **2020 84.2%**, 2021 93.7%, 2022 99.6%, 2023 99.2%, 2024 100%, 2025 94.8% | **fail in 2020** |
| No unexplained gap over 5 sessions | runs of 40, 16 and 12 sessions; all are catalogued archive outages | explained, not short |
| Usable origin rows, at least 1,250 | 1,441 | pass |
| Final test, at least 500 common eligible forecasts | 500 | pass at the minimum |
| FinBERT coverage, at least 98% per included session | 100% of the designated sample in every complete window | pass |
| Resources | extraction and scoring ran inside 15 GiB RAM with the sentiment gate passing | pass |

## CHG-002 — reduced-study split and a documented 2020 continuity exception

```text
Trigger and evidence: GDELT's archive lacks batches for 2020-09-24–2020-11-18,
  2021-07-29–2021-08-19 and 2025-06-12–2025-07-02. 2020 has 84.2% complete windows.
  Only 454 usable rows have a target end by 2021-12-31.
Existing decision: blueprint §16.1 GDELT alternative needs at least 500 usable training rows
  from 2020–2021; §6.2 needs 90% complete windows in every year.
Options: (a) strict contiguous interval after the 2020 gap: 1,188 usable rows, below 1,250,
  i.e. prototype only; (b) keep all complete windows and apply the §6.2 reduced-study rule;
  (c) lower the completeness threshold until 2020 passes.
Decision: (b). The reduced-study rule is the blueprint's own fallback. Incomplete windows are
  excluded from every training and scoring row, so the 2020 gap removes rows rather than
  contaminating them. (c) is rejected: no threshold was changed.
Consequence, stated plainly: the study is NOT the planned full confirmatory study. It is a
  qualified, reduced-power historical-proxy study. Under the strict reading (a) its sample
  would be prototype grade. Every result must carry this label.
Split, fixed from eligibility counts only:
  training    691 usable rows, target end 2019-12-24 – 2022-12-12
  development 250 usable rows, target end 2022-12-13 – 2023-12-13
  final test  500 usable rows, target end 2023-12-14 – 2025-12-31
Affects: blueprint §6.2, §16.1; M4-02 (one development fold, 18 linear + 24 tree runs);
  search-plan design "reduced_study".
Invalidated artifacts: none. No M2 score for 2023–2025 was ever computed or published, so
  moving 2023 into development reuses no inspected outcome.
```

The 2021 and 2025 gaps fall inside training and the final test respectively. The test loses 13 sessions in June–July 2025; they are reported as missing forecasts, not filled.

## CHG-003 — frozen 27% content-hash sample for sentiment scoring

```text
Trigger: 3,582,698 unique retained titles; measured idle throughput 62–117 titles/s on 4 CPUs.
  Scoring all of them would take about 14 hours; the blueprint's upper planning cap is 1,000,000.
Decision (rule frozen in the ingestion gate before the corpus count was known):
  rate = floor(1,000,000 / 3,582,698, 2 decimals) = 0.27; a title is scored iff the first
  32 bits of its SHA-256 are below 0.27 * 2^32. 967,729 titles designated and scored.
Effect: news counts use all retained events. Sentiment means and ratios are computed on the
  sampled events. negative_log_intensity divides the summed negative probability by 0.27.
  A regular window has roughly 500 scored headlines.
Limitation: the sample adds sampling noise to every sentiment aggregate. This can only
  weaken a real sentiment signal; it cannot create one.
```

## Sentiment inference record (M3-01, M3-02)

- Model files: all five SHA-256 values equal the September benchmark record; fingerprint `ca5cf73e…14e9`; CPU FP32, max length 128, batch 32, 4 threads.
- 967,729 titles in about 3 h 50 min of scoring (three resumable runs); every probability row validated on write.
- Truncation: 72 titles (0.007%) exceed 128 tokens, far below the 1% trigger; 128 is kept. Mean length 19.5 tokens.
- Predicted class shares over scored unique titles: neutral 60.9%, negative 20.4%, positive 18.7%.
- INT8 was not attempted; FP32 fit the budget.

### 200-headline domain audit (§14.3) — agent-rated, single rater

A seeded sample of 200 training-period titles, stratified by year and predicted class (class-balanced, so not a population accuracy estimate), was rated by the implementing agent. **No human annotator was involved.** The sample and labels are private; no title text is committed.

| Measure | Result |
|---|---|
| Out of domain or unusable (not business, market or economic news) | 28 clear, up to 32 with marginal cases: 14–16% |
| In-domain titles | about 170 |
| Rater agrees with the predicted class | about 140 / 170 = 82% (negative 76%, positive 83%, neutral 89%) |
| Outright polarity inversions (positive vs negative) | 5 / 170 = 3% |

Findings:

- The 20% unusable trigger is not reached, but one title in seven is noise: crime, local politics, health and product pages that merely carry a market theme tag.
- Recurring error: headlines of the form "rebound / higher after a fall" and idioms ("crushing it") are scored negative. This is a wording weakness, not a systematic polarity flip.
- Mixed headlines ("stocks, oil slip but Chinese stocks rally") are forced into one class.
- Consequence for interpretation: sentiment aggregates describe the tone of a broad, noisy web-title feed, not curated financial headlines.

## Feature table and eligibility (M3-03, M3-04)

- Table `news`-backed rows: 2,286 origins; 1,441 usable. Ineligibility causes (a row can have several): news warm-up 773, incomplete feed 782, market history 64.
- Usable rows by target year: 2019 5, 2020 213, 2021 236, 2022 250, 2023 248, 2024 252, 2025 237.
- Future-append invariance, cutoff boundaries, gap handling, lagged sentiment and the coverage gate are covered by synthetic fixtures.

## Gate checks before development experiments

- 106 tests pass; Ruff lint/format and strict mypy pass.
- A fully synthetic rehearsal (synthetic prices, synthetic news, fake scorer) ran admit → develop → preregister → evaluate → report. With random news it found Q2 equal to Q1, as it should.
- The development command computes nothing outside 2022-12-13 – 2023-12-13.
- Risks reviewed: Class B timing (three delay sensitivities are declared); sampled sentiment; one development fold only; a final test at the 500-row minimum.

## Open items

1. An independent human review of the domain audit would strengthen it; none is available in this session.
2. The market snapshot was refetched on 2026-11-24; FRED's rolling window now starts 2016-11-25. Market history before the news period is still more than three years.
