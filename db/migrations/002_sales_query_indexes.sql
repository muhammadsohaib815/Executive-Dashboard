-- New indexes validated against session-local copies of the dashboard data.
-- Run each statement separately with autocommit; never wrap this file in BEGIN.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sales_data_product_month ON public.sales_data (product_no, reporting_month);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sales_data_first_buy_positive ON public.sales_data (position_code, cust_number, reporting_month) WHERE COALESCE(net_sale_value, 0) > 0;
