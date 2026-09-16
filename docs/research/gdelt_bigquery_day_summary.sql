-- Bounded, outcome-blind GDELT-title feasibility summary for exactly one UTC day.
-- StandardSQL. Run a dry run first. The parameter must be supplied as DATE.
-- Verify all referenced columns against gdelt_bigquery_schema.sql before executing.
SELECT
  DATE(_PARTITIONTIME) AS archive_day_utc,
  COUNT(*) AS gkg_rows,
  COUNTIF(REGEXP_CONTAINS(Extras, r'<PAGE_TITLE>.+?</PAGE_TITLE>')) AS titled_rows,
  COUNTIF(TranslationInfo IS NULL) AS null_translation_info_rows,
  COUNTIF(REGEXP_CONTAINS(TranslationInfo, r'srclc:eng;')) AS source_language_english_rows,
  COUNTIF(REGEXP_CONTAINS(Extras, r'<PAGE_PRECISEPUBTIMESTAMP>')) AS precise_time_rows,
  COUNT(DISTINCT DocumentIdentifier) AS distinct_document_urls,
  COUNT(DISTINCT SourceCommonName) AS distinct_source_domains
FROM
  `gdelt-bq.gdeltv2.gkg_partitioned`
WHERE
  _PARTITIONTIME >= TIMESTAMP(@pilot_day)
  AND _PARTITIONTIME < TIMESTAMP(DATE_ADD(@pilot_day, INTERVAL 1 DAY));
