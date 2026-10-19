-- PLAN ONLY: rollback is safe only while the retained source table contains
-- every write accepted after cutover. This guard prevents accidental execution.
DO $$
BEGIN
    RAISE EXCEPTION 'PLAN ONLY: verify write replay and use an approved maintenance window';
END
$$;

-- Future rollback outline (keep commented until separately approved):
-- BEGIN;
-- LOCK TABLE public.sales_data IN ACCESS EXCLUSIVE MODE;
-- ALTER TABLE public.sales_data RENAME TO sales_data_partitioned_failed;
-- ALTER TABLE public.sales_data_unpartitioned_backup RENAME TO sales_data;
-- COMMIT;
--
-- Then reinstall/verify summary-dirty and cache-generation triggers, refresh
-- affected summaries, validate all months, ANALYZE the restored table, and only
-- later remove sales_data_partitioned_failed after explicit review.

