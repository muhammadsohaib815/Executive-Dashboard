DO $$
DECLARE
    source_table text;
    trigger_name text;
BEGIN
    FOREACH source_table IN ARRAY ARRAY[
        'sales_data', 'target_data', 'staff_master', 'call_data',
        'call_data_rollup', 'sales_monthly_summary_refresh_state'
    ] LOOP
        IF to_regclass('public.' || source_table) IS NOT NULL THEN
            trigger_name := 'dashboard_cache_invalidate_' || source_table;
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', trigger_name, source_table);
        END IF;
    END LOOP;
END;
$$;

DROP FUNCTION IF EXISTS public.bump_dashboard_cache_generation();
DROP TABLE IF EXISTS public.dashboard_cache_generation;

