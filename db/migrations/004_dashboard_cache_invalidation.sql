-- Shared generation used by bounded in-process API caches in every worker.
CREATE TABLE IF NOT EXISTS public.dashboard_cache_generation (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    generation bigint NOT NULL DEFAULT 1,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO public.dashboard_cache_generation (singleton)
VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE OR REPLACE FUNCTION public.bump_dashboard_cache_generation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE public.dashboard_cache_generation
       SET generation = generation + 1,
           changed_at = clock_timestamp()
     WHERE singleton = true;
    RETURN NULL;
END;
$$;

DO $$
DECLARE
    source_table text;
    trigger_name text;
BEGIN
    FOREACH source_table IN ARRAY ARRAY[
        'sales_data', 'target_data', 'staff_master', 'call_data',
        'call_data_rollup', 'pharma_provider_calls', 'fmcg_exception',
        'fmcg_cust_call', 'sales_monthly_summary_refresh_state'
    ] LOOP
        IF to_regclass('public.' || source_table) IS NOT NULL THEN
            trigger_name := 'dashboard_cache_invalidate_' || source_table;
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I', trigger_name, source_table);
            EXECUTE format(
                'CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.%I '
                'FOR EACH STATEMENT EXECUTE FUNCTION public.bump_dashboard_cache_generation()',
                trigger_name, source_table
            );
        END IF;
    END LOOP;
END;
$$;

