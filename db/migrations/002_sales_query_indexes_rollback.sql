-- Remove only the two indexes introduced by 002. Preserve all earlier indexes.
-- Run each statement separately with autocommit; never wrap this file in BEGIN.
DROP INDEX CONCURRENTLY IF EXISTS public.idx_sales_data_first_buy_positive;
DROP INDEX CONCURRENTLY IF EXISTS public.idx_sales_data_product_month;
