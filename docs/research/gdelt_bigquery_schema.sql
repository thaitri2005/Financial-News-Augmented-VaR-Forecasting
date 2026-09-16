-- Read schema before using any GDELT extraction SQL.
-- StandardSQL. This metadata query has no date scan and must run first.
SELECT
  column_name,
  data_type,
  is_nullable,
  ordinal_position
FROM
  `gdelt-bq.gdeltv2.INFORMATION_SCHEMA.COLUMNS`
WHERE
  table_name = 'gkg_partitioned'
ORDER BY
  ordinal_position;
