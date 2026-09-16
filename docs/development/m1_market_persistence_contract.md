# M1-04B market and label persistence contract

## Scope

This increment creates the first private, immutable, normalized market dataset from the retained FRED `SP500` and Cboe `VIX` snapshots. It writes small Parquet tables with Apache Arrow 25.0.1 because Parquet supplies typed columns, column projection, cross-tool interoperability, and integrity-verifiable files without requiring a database service. DuckDB remains a later query layer; it is not needed to publish this small first dataset.

The dataset contains observations and future labels, never features, forecasts, model parameters, news rows, or any final-period result report. A human-readable manifest carries the source, parser, calendar, availability-policy, table-schema, file checksum and row-count lineage. Every manifest and directory is content-identified from its inputs. A consumer reads only a committed directory and rechecks the manifest identity and all Parquet file checksums.

## Calendar and right edge

The first frozen XNYS schedule ends on 2025-12-31. M1-04B creates a second immutable snapshot through 2026-01-02, with the same start/profile/package/tzdata settings. It compares every overlapping origin record with the original snapshot before publishing derived data. That January 2 origin supplies the cutoff at which the December 31 close becomes usable under the declared historical prior-session assumption. This restores the 2025-12-30 origin's December 30→31 label. The 2025-12-31 origin targets January 2 2026 and remains outside the study because membership is keyed by `target_end_session <= 2025-12-31`; it is never brought in by an origin-date filter.

## Table semantics

`market_observations.parquet` has one retained source row within the extended calendar bounds. It preserves both observed values and FRED placeholders. A value is nullable only for a source placeholder; `quality_status` distinguishes `valid_xnys_session`, `valid_off_xnys_session`, and `source_placeholder_off_xnys_session`. Cboe closure rows are retained as off-XNYS observations so their exclusion is reproducible. Scheduled session close and historical availability timestamp are nullable when no XNYS session/cutoff supports them. `available_at_utc` is a policy proxy, not a claimed original release timestamp.

`labels.parquet` contains only labels with two actual adjacent SP500 closes and explicit later availability. It records start/end scheduled close timestamps, decimal simple return, raw target source lineage, label/calendar/version IDs, and the non-null market manifest ID. `label_exclusions.parquet` records every skipped origin/reason and target-end study-horizon flag. Missing prices, unavailable right-edge prices and placeholders never become a zero/multi-session return.

## Publication and recovery

The materializer constructs tables in memory for this bounded 2016–2026 source slice, writes Parquet plus manifest into one same-volume staging directory, fsyncs regular files, validates the staged directory, then performs a single directory rename under `data/derived/market/`. Repeated execution with unchanged inputs reloads the existing valid dataset; a conflicting directory fails. Partial staging directories are invisible to readers and can be inspected/recovered later. Corrected parser/source/calendar/availability inputs produce a new dataset ID and do not overwrite old data.

This uses the project's one-writer local protocol. The normalization CLI requires a fresh doctor pass at or above 3 GiB free RAM. It must run as one process, without NLP/model imports. Any later model/report consuming a changed dataset ID is stale by definition and must be rerun.

## Executed evidence

On 2026-09-15T20:56:36Z, the normalization preflight had 7,084,969,984 available RAM bytes and 75,662,659,584 free disk bytes. The locked offline command published dataset 7819b4c29e1822c6829bf7ea2f5ec8570ba4995eb7f9e4d017722412701a1d8a and calendar 628049ff60f65d07a7dbeba6ff57dfe87a33bd9906b79a26603b2152926fe5e4. The reloaded manifest records 4,792 observation rows, 2,336 labels, and two exclusions: the 2025-12-31 origin is outside the declared target-end horizon and the 2026-01-02 origin lacks a following cutoff. The original 2,337 origins match the extended snapshot exactly. File hashes, counts, source raw hashes and availability basis are in the [dated dataset evidence](../research/market_dataset_20260916.json). No outcomes, return values, distributions, or model results appear in that evidence.
