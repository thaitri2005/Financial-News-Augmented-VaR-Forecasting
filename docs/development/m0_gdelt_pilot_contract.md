# M0-04 GDELT title feasibility-pilot contract

## Purpose and decision boundary

This task tests whether a free GDELT route can provide a complete, temporally qualified title series at laptop scale. It does **not** select features based on returns, ingest a multi-year corpus, or admit GDELT as the primary source. A catalog listing confirms that archive files exist; it does not confirm their title eligibility, relevance, source-language precision, duplicate policy, publisher timestamp, or full historical release timing.

## Completed bounded evidence

The public `masterfilelist.txt` was read only through HTTP range requests. The catalog was 127,654,599 bytes at the observed `Last-Modified` value; the probe used 26 requests and 1,703,936 bytes, retaining only range hashes and derived file metadata. Both 2020-03-16 and 2022-06-13 list all 96 expected 15-minute GKG ZIP batches. Their listed compressed sizes are 759,200,749 and 494,756,325 bytes. The [catalog report](../research/gdelt_catalog_pilot_20260916.json) is immutable evidence of that one observation.

This supports a firm local-archive decision: do not download a raw multi-year GKG backfill. Even the two verified daily sizes are 0.46–0.71 GiB. A full archive would exceed the laptop's available disk and has no mechanism to prove daily eligibility merely by downloading it. Existing retained 15-minute 2020/2022/2023/2025 samples separately prove that post-September-2019 `PAGE_TITLE` can occur; they do not estimate full-day coverage.

## Proposed free BigQuery sandbox pilot

Before any extraction query, run [schema SQL](../research/gdelt_bigquery_schema.sql) in a personal no-billing BigQuery sandbox and save its result as a dated source-schema record. Abort if it cannot access the public table or any required column is absent. BigQuery schema is external mutable state; do not rely on old examples as its current contract.

For each of the two predeclared UTC pilot days, run [the daily summary](../research/gdelt_bigquery_day_summary.sql) as a **dry run first**, with `--maximum_bytes_billed=10737418240` (10 GiB), explicit `--location=US`, and a `DATE` parameter. A dry run above 10 GiB is a no-go for this first executed pilot. If the dry run is within cap, execute the same count-only query with the same cap, save job metadata/processed bytes and output JSON, and do not export titles yet.

```powershell
# Requires a user-owned Google Cloud project with BigQuery sandbox enabled and bq authenticated.
bq query --use_legacy_sql=false --location=US --format=prettyjson `
  --parameter=pilot_day:DATE:2020-03-16 < docs/research/gdelt_bigquery_schema.sql

bq query --dry_run --use_legacy_sql=false --location=US `
  --maximum_bytes_billed=10737418240 --parameter=pilot_day:DATE:2020-03-16 `
  < docs/research/gdelt_bigquery_day_summary.sql
```

Repeat only for `2022-06-13` after recording the first job. `LIMIT` is not a cost control on an unclustered table. The summary asks only for counts, titles, time/language metadata presence, distinct URLs/domains and the constrained partition; it exposes no title text and has no market outcome input.

## Admission remains open until all of these pass

1. Current schema and public-table access are recorded.
2. The two daily summary dry runs/queries stay inside the stated free cap, with observed scan bytes captured.
3. A later small title-export query has a separately declared result-byte cap, exhaustive query semantics, source/date/relevance policy and raw-response manifest.
4. At least one complete calendar week per proposed year plus DST/early-close/stress windows are audited for completion, title/time precision, source transitions and continuity.
5. Archive batch time remains labelled a historical proxy. It is not silently upgraded to publisher publication or delivery time.

If the sandbox pilot exceeds the cap, lacks public access, or cannot support the required coverage, close GDELT as a complete-title source and move to the user's offered free Alpaca entitlement pilot. No billing upgrade, publisher-body scraping or source splice is allowed.
