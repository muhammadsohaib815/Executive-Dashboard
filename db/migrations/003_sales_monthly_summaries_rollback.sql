-- Apply in one transaction. Removes derived data and change tracking only.
-- public.sales_data and public.target_data are not modified.

DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_insert ON public.sales_data;
DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_update ON public.sales_data;
DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_delete ON public.sales_data;
DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_truncate ON public.sales_data;
DROP FUNCTION IF EXISTS public.mark_sales_monthly_summary_dirty();

DROP TABLE IF EXISTS public.sales_monthly_customer_summary;
DROP TABLE IF EXISTS public.sales_monthly_position_product_summary;
DROP TABLE IF EXISTS public.sales_monthly_product_summary;
DROP TABLE IF EXISTS public.sales_monthly_position_summary;
DROP TABLE IF EXISTS public.sales_monthly_summary_refresh_state;
DROP TABLE IF EXISTS public.sales_monthly_summary_dirty_period;
