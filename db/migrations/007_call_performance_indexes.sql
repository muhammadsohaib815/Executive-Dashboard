-- Support month and scoped employee lookups in the Call Performance panel.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fmcg_cust_call_month_ff ON public.fmcg_cust_call (month, ff_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fmcg_exception_month_ff ON public.fmcg_exception (month, ff_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pharma_provider_calls_month_ff ON public.pharma_provider_calls (month, ff_id);
