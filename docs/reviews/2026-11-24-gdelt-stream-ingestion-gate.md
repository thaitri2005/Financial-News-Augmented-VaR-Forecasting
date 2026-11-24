# 2026-11-24 — GDELT streaming pilot and bulk-ingestion gate (M0-04, M1-05)

**Scope:** resumption review after ten weeks of inactivity; news-source access route; gate before bulk news acquisition. **Reviewer role:** implementing agent (self-review, not independent). **Outcome:** bulk title extraction **approved to run**; source **admission is not decided here** — it depends on the continuity audit recorded after extraction.

## Resumption findings

- The repository had one commit (2026-09-16). `PROJECT_STATUS.md` still said "no commits"; corrected in this increment.
- Work resumed in a cloud Linux container (4 CPUs, 15 GiB RAM, about 60 GiB free disk), not the original Windows laptop. Git-ignored `data/` did not travel with the repository, so the September private snapshots, calendars, market dataset and M2 ledgers are absent here and are rebuilt from public sources under new identities.
- The container's network policy initially blocked every data host. The user approved a dedicated environment allowing FRED, Cboe, GDELT, Hugging Face and the PyTorch CPU wheel host. No credential, paid service or account was used.
- The live sentiment resource gate that held M3-01 (5 GiB available RAM) passes here.

## CHG-001 — streaming filter-and-discard replaces the BigQuery sandbox pilot

```text
Trigger and evidence: M0-04 waited on a user-owned BigQuery sandbox or Alpaca key. Neither exists.
  The public archive is reachable from this container at roughly 50 MB/s; one UTC day
  (96 batches, 0.46–0.71 GiB) is fetched, verified and filtered in 10–14 s.
Existing decision / problem: blueprint §5.4 rejected a local GKG archive because 1.1–1.9 TiB
  could not be stored or transferred on the laptop, and routed extraction through BigQuery.
Options: (a) wait for BigQuery/Alpaca access; (b) stream each catalogued batch, verify it
  against the catalog, keep only relevance-matched rows, discard the payload.
Decision: (b). It needs no account, costs nothing, stores about 1 MB per day, and yields a
  per-batch completeness ledger that a BigQuery count query would not.
Authorization basis: free data, no external account, within the accepted source list (§5.1,
  §5.9 step 2). The user asked on 2026-11-24 to obtain a free source and finish the project.
Affects: blueprint §5.4, §5.9, §18.3; M0-04, M1-05; new adapter gdelt_gkg_stream_v1.
Invalidated artifacts: none. The BigQuery contract and SQL remain as an unexecuted alternative.
Revalidation / rollback: every batch is re-fetchable by URL and checked against the catalog
  size and MD5; a day with any failed batch is retried on the next run.
```

**Deviation from §5.4 "retain the raw batch/hash":** the raw ZIP payloads are not retained (1.14 TiB for the range). Retained instead: the dated master catalog (SHA-256 `3797ec66…9622f7`, 129,791,572 bytes), and for every batch its catalog byte count, verified MD5, row counts and status. The archive is immutable and public, so a batch can be re-fetched and re-verified.

## Pilot evidence (the two days predeclared in the M0-04 contract)

| UTC day | Batches verified | Compressed bytes | GKG rows | Rows with `PAGE_TITLE` | Rows with `ECON_STOCKMARKET` | of which US-located |
|---|---:|---:|---:|---:|---:|---:|
| 2020-03-16 | 96 / 96 | 759,200,749 | 191,649 | 191,649 | 16,879 | 9,642 |
| 2022-06-13 | 96 / 96 | 494,756,325 | 120,983 | 120,982 | 7,243 | 3,228 |

- Byte totals equal the September catalog pilot exactly; every payload matched its catalog MD5.
- One malformed row in 312,632; no translated rows in the English feed.
- Unique US-located titles: 4,354 and 1,829. Syndication is heavy, so chronological deduplication matters.

## Frozen before any return is joined

These rules were fixed on 2026-11-24 from metadata only. No market outcome was read while choosing them.

| Rule | Value |
|---|---|
| Extraction range | UTC 2019-09-01 through 2025-12-31 (2,314 days; 1.14 TiB catalogued) |
| Extraction filter | whole V1 theme code `ECON_STOCKMARKET` |
| Study relevance `gdelt_en_web_us_stockmarket_title_v1` | web collection, untranslated, at least one US location, non-empty title of at least 10 characters containing a letter |
| Normalization `headline_text_v1` | HTML-unescape, strip markup, NFC, collapse whitespace; case, numbers and punctuation kept |
| Dedup `exact_casefold_title_or_url_72h_v1` | chronological; same case-folded title or same URL within 72 hours is suppressed; each occurrence refreshes the lookback |
| Availability (Class B) | batch time + 15 minutes; sensitivities 60 and 240 minutes and a one-session delay |
| Window completeness | a window is `feed_complete` when at least 95% of its expected 15-minute batches were catalogued, verified and parsed |
| Sentiment scoring cap | at most 1,000,000 unique titles. If the deduplicated corpus is larger, score a frozen content-hash probability sample at rate `floor(1e6 / unique titles, 2 decimals)`; counts always use the full retained feed |

The 1,000,000 cap is the blueprint §18.2 upper planning cap. Measured single-core throughput under load was about 21 titles/s, which makes an unsampled corpus of several million titles exceed the session budget. Sampling by content hash is the §18.2 "frozen probability sampling rule"; it is disclosed in every result and changes `negative_log_intensity` to a Horvitz–Thompson estimate.

## Known catalog gaps (source-quality evidence, decided before outcomes)

The catalog has no entry, and the archive returns HTTP 404, for batches in these ranges:

| UTC range | Catalogued batches per day |
|---|---|
| 2020-09-24 – 2020-11-18 | 8–89 of 96 |
| 2021-07-29 – 2021-08-19 | 43–87 of 96 |
| 2023-03-22 – 2023-03-23 | 15 and 44 of 96 |
| 2025-06-12 – 2025-07-02 | 0–87 of 96; none at all 2025-06-15 – 2025-07-01 |

Windows overlapping these ranges will be `feed_complete=false` and ineligible for the paired comparison. Whether the per-year 90% continuity rule in blueprint §6.2 passes is evaluated in the admission audit after extraction, not assumed here.

## Checks

- `tests/test_gdelt_stream.py`, `tests/test_news.py`: 13 synthetic fixtures pass (whole-theme matching, absent vs failed vs corrupt batches, resume, checksum enforcement, dedup causality, cutoff boundaries, coverage). No network in tests.
- Ruff lint/format and strict mypy pass on `src/newsvar`.
- Pinned FinBERT revision `5fcfed04…745db` downloaded; all five file hashes equal the September benchmark record.
- Fresh market snapshot: 2,287 XNYS sessions from 2016-11-25 with a FRED close and Cboe VIX on every one; dataset `66a1ae68…d98b`, 2,286 labels. FRED's rolling window no longer serves 2016-09-15 – 2016-11-24.

## Open items

1. Continuity and sample-size admission audit after extraction (blueprint §6.2).
2. FinBERT throughput on an idle machine, then the scoring rate decision above.
3. The 200-headline domain audit (§14.3) needs human labels; an agent can sample and tabulate but cannot stand in for an annotator.
