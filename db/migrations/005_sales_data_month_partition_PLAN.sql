-- PLAN ONLY: this file deliberately stops before any schema statement.
-- Partitioning is deferred at the current 221,107-row scale.
DO $$
BEGIN
    RAISE EXCEPTION 'PLAN ONLY: complete the partition readiness checklist and use a test database';
END
$$;

-- Future test-database outline (keep commented until separately approved):
--
-- CREATE TABLE public.sales_data_partitioned
--   (LIKE public.sales_data INCLUDING DEFAULTS INCLUDING GENERATED
--    INCLUDING IDENTITY INCLUDING STORAGE INCLUDING COMMENTS)
--   PARTITION BY RANGE (transaction_date);
--
-- CREATE TABLE public.sales_data_2026_07 PARTITION OF public.sales_data_partitioned
--   FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
-- CREATE TABLE public.sales_data_2026_08 PARTITION OF public.sales_data_partitioned
--   FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
-- CREATE TABLE public.sales_data_2026_09 PARTITION OF public.sales_data_partitioned
--   FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
-- CREATE TABLE public.sales_data_default PARTITION OF public.sales_data_partitioned DEFAULT;
--
-- CREATE INDEX sales_data_partitioned_period_position
--   ON public.sales_data_partitioned (reporting_month, fiscal_year, position_code);
-- CREATE INDEX sales_data_partitioned_position_period
--   ON public.sales_data_partitioned (position_code, reporting_month, fiscal_year);
--
-- INSERT INTO public.sales_data_partitioned SELECT * FROM public.sales_data;
-- ANALYZE public.sales_data_partitioned;
--
-- Required gates before cutover:
--   * stable unique source key defined;
--   * zero default-partition rows for known history;
--   * exact row counts and KPI checksums by month;
--   * raw API queries include matching transaction_date bounds;
--   * summary-dirty and cache-generation triggers recreated and tested;
--   * grants, owners, import jobs, and dependent objects reviewed;
--   * write freeze and replayable final-delta procedure rehearsed.
--
-- Cutover only during an approved write freeze:
-- BEGIN;
-- LOCK TABLE public.sales_data IN ACCESS EXCLUSIVE MODE;
-- ALTER TABLE public.sales_data RENAME TO sales_data_unpartitioned_backup;
-- ALTER TABLE public.sales_data_partitioned RENAME TO sales_data;
-- COMMIT;

