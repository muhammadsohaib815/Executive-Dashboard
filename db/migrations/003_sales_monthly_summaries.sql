-- PostgreSQL 15+ (NULLS NOT DISTINCT). Apply as one transaction before backfill.
-- Dashboard queries use these tables only after a complete validated backfill.

CREATE TABLE IF NOT EXISTS public.sales_monthly_position_summary (
    reporting_month text NOT NULL,
    fiscal_year text NOT NULL,
    team text,
    position_code text,
    transaction_count bigint NOT NULL,
    gross_tp_value numeric,
    net_sale_value numeric,
    net_wo_reg_disc_value numeric,
    units numeric,
    net_qty numeric,
    cyp numeric,
    discounts numeric,
    bonus_discount numeric,
    mnp_commission numeric,
    net_value numeric,
    positive_net_sale_value numeric,
    positive_tp_sale_value numeric,
    negative_net_sale_abs numeric,
    return_impact_value numeric,
    net_sale_value_rows bigint NOT NULL,
    net_qty_rows bigint NOT NULL,
    positive_sale_rows bigint NOT NULL,
    active_customer_count bigint NOT NULL,
    transacting_customer_count bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS public.sales_monthly_product_summary (
    reporting_month text NOT NULL,
    fiscal_year text NOT NULL,
    team text,
    product_no text,
    group_on text,
    prd_name text,
    transaction_count bigint NOT NULL,
    gross_tp_value numeric,
    net_sale_value numeric,
    net_wo_reg_disc_value numeric,
    units numeric,
    net_qty numeric,
    cyp numeric,
    discounts numeric,
    bonus_discount numeric,
    mnp_commission numeric,
    net_value numeric,
    positive_net_sale_value numeric,
    positive_tp_sale_value numeric,
    negative_net_sale_abs numeric,
    return_impact_value numeric,
    net_sale_value_rows bigint NOT NULL,
    net_qty_rows bigint NOT NULL,
    positive_sale_rows bigint NOT NULL,
    active_customer_count bigint NOT NULL,
    transacting_customer_count bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS public.sales_monthly_customer_summary (
    reporting_month text NOT NULL,
    fiscal_year text NOT NULL,
    team text,
    position_code text,
    product_no text,
    group_on text,
    cust_number text,
    cust_name text,
    has_positive_sale boolean NOT NULL,
    transaction_count bigint NOT NULL,
    gross_tp_value numeric,
    net_sale_value numeric,
    net_wo_reg_disc_value numeric,
    units numeric,
    net_qty numeric,
    cyp numeric,
    discounts numeric,
    bonus_discount numeric,
    mnp_commission numeric,
    net_value numeric,
    positive_net_sale_value numeric,
    positive_tp_sale_value numeric,
    negative_net_sale_abs numeric,
    return_impact_value numeric,
    net_sale_value_rows bigint NOT NULL,
    net_qty_rows bigint NOT NULL,
    positive_sale_rows bigint NOT NULL,
    active_customer_count bigint NOT NULL,
    transacting_customer_count bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS public.sales_monthly_position_product_summary (
    reporting_month text NOT NULL,
    fiscal_year text NOT NULL,
    team text,
    position_code text,
    product_no text,
    group_on text,
    prd_name text,
    transaction_count bigint NOT NULL,
    gross_tp_value numeric,
    net_sale_value numeric,
    net_wo_reg_disc_value numeric,
    units numeric,
    net_qty numeric,
    cyp numeric,
    discounts numeric,
    bonus_discount numeric,
    mnp_commission numeric,
    net_value numeric,
    positive_net_sale_value numeric,
    positive_tp_sale_value numeric,
    negative_net_sale_abs numeric,
    return_impact_value numeric,
    net_sale_value_rows bigint NOT NULL,
    net_qty_rows bigint NOT NULL,
    positive_sale_rows bigint NOT NULL,
    active_customer_count bigint NOT NULL,
    transacting_customer_count bigint NOT NULL
);

-- Every grain key is unique even if a future import contains NULL dimensions.
CREATE UNIQUE INDEX IF NOT EXISTS sales_monthly_position_summary_grain
    ON public.sales_monthly_position_summary
    (reporting_month, fiscal_year, team, position_code) NULLS NOT DISTINCT;
CREATE UNIQUE INDEX IF NOT EXISTS sales_monthly_product_summary_grain
    ON public.sales_monthly_product_summary
    (reporting_month, fiscal_year, team, product_no, group_on) NULLS NOT DISTINCT;
CREATE UNIQUE INDEX IF NOT EXISTS sales_monthly_customer_summary_grain
    ON public.sales_monthly_customer_summary
    (reporting_month, fiscal_year, team, position_code, product_no, group_on,
     cust_number, cust_name) NULLS NOT DISTINCT;
CREATE UNIQUE INDEX IF NOT EXISTS sales_monthly_position_product_summary_grain
    ON public.sales_monthly_position_product_summary
    (reporting_month, fiscal_year, team, position_code, product_no, group_on)
    NULLS NOT DISTINCT;

CREATE INDEX IF NOT EXISTS sales_monthly_position_lookup
    ON public.sales_monthly_position_summary (reporting_month, fiscal_year, position_code);
CREATE INDEX IF NOT EXISTS sales_monthly_product_group_lookup
    ON public.sales_monthly_product_summary (reporting_month, fiscal_year, group_on);
CREATE INDEX IF NOT EXISTS sales_monthly_customer_position_lookup
    ON public.sales_monthly_customer_summary
    (reporting_month, fiscal_year, position_code, cust_number);
CREATE INDEX IF NOT EXISTS sales_monthly_customer_product_lookup
    ON public.sales_monthly_customer_summary
    (reporting_month, fiscal_year, product_no, cust_number);
CREATE INDEX IF NOT EXISTS sales_monthly_position_product_lookup
    ON public.sales_monthly_position_product_summary
    (reporting_month, fiscal_year, position_code, product_no);

CREATE TABLE IF NOT EXISTS public.sales_monthly_summary_refresh_state (
    reporting_month text NOT NULL,
    fiscal_year text NOT NULL,
    source_rows bigint NOT NULL,
    refreshed_at timestamptz NOT NULL,
    PRIMARY KEY (reporting_month, fiscal_year)
);

CREATE TABLE IF NOT EXISTS public.sales_monthly_summary_dirty_period (
    reporting_month text NOT NULL,
    fiscal_year text NOT NULL,
    revision bigint NOT NULL DEFAULT 1,
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (reporting_month, fiscal_year)
);

-- Statement triggers record both sides of corrections. A TRUNCATE marks all
-- previously refreshed periods. The refresh job performs the expensive work.
CREATE OR REPLACE FUNCTION public.mark_sales_monthly_summary_dirty()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.sales_monthly_summary_dirty_period (reporting_month, fiscal_year)
        SELECT DISTINCT reporting_month, fiscal_year FROM new_rows
        WHERE reporting_month IS NOT NULL AND fiscal_year IS NOT NULL
        ON CONFLICT (reporting_month, fiscal_year) DO UPDATE
        SET revision = sales_monthly_summary_dirty_period.revision + 1,
            changed_at = clock_timestamp();
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO public.sales_monthly_summary_dirty_period (reporting_month, fiscal_year)
        SELECT reporting_month, fiscal_year FROM old_rows
        WHERE reporting_month IS NOT NULL AND fiscal_year IS NOT NULL
        UNION
        SELECT reporting_month, fiscal_year FROM new_rows
        WHERE reporting_month IS NOT NULL AND fiscal_year IS NOT NULL
        ON CONFLICT (reporting_month, fiscal_year) DO UPDATE
        SET revision = sales_monthly_summary_dirty_period.revision + 1,
            changed_at = clock_timestamp();
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO public.sales_monthly_summary_dirty_period (reporting_month, fiscal_year)
        SELECT DISTINCT reporting_month, fiscal_year FROM old_rows
        WHERE reporting_month IS NOT NULL AND fiscal_year IS NOT NULL
        ON CONFLICT (reporting_month, fiscal_year) DO UPDATE
        SET revision = sales_monthly_summary_dirty_period.revision + 1,
            changed_at = clock_timestamp();
    ELSIF TG_OP = 'TRUNCATE' THEN
        INSERT INTO public.sales_monthly_summary_dirty_period (reporting_month, fiscal_year)
        SELECT reporting_month, fiscal_year
        FROM public.sales_monthly_summary_refresh_state
        ON CONFLICT (reporting_month, fiscal_year) DO UPDATE
        SET revision = sales_monthly_summary_dirty_period.revision + 1,
            changed_at = clock_timestamp();
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_insert ON public.sales_data;
CREATE TRIGGER sales_monthly_summary_dirty_insert
AFTER INSERT ON public.sales_data
REFERENCING NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION public.mark_sales_monthly_summary_dirty();

DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_update ON public.sales_data;
CREATE TRIGGER sales_monthly_summary_dirty_update
AFTER UPDATE ON public.sales_data
REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
FOR EACH STATEMENT EXECUTE FUNCTION public.mark_sales_monthly_summary_dirty();

DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_delete ON public.sales_data;
CREATE TRIGGER sales_monthly_summary_dirty_delete
AFTER DELETE ON public.sales_data
REFERENCING OLD TABLE AS old_rows
FOR EACH STATEMENT EXECUTE FUNCTION public.mark_sales_monthly_summary_dirty();

DROP TRIGGER IF EXISTS sales_monthly_summary_dirty_truncate ON public.sales_data;
CREATE TRIGGER sales_monthly_summary_dirty_truncate
AFTER TRUNCATE ON public.sales_data
FOR EACH STATEMENT EXECUTE FUNCTION public.mark_sales_monthly_summary_dirty();
