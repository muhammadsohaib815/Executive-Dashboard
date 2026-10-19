-- Existing dashboard indexes previously created at application import.
-- Run each statement separately with autocommit; never wrap this file in BEGIN.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_position_code ON public.staff_master (position_code);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_reports_to ON public.staff_master (report_to_position_code);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_designation_employee ON public.staff_master (designation_name, employee_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_designation_normalized ON public.staff_master (UPPER(TRIM(designation_name)), TRIM(designation_name));
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_geo ON public.staff_master (region_name, zone_name, sub_zone, dept_territory_code);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_employee_name ON public.staff_master (employee_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_region_name ON public.staff_master (region_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_zone_name ON public.staff_master (zone_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_sub_zone ON public.staff_master (sub_zone);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_dept_territory ON public.staff_master (dept_territory_code);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_employee_prefix ON public.staff_master (LOWER(employee_name) text_pattern_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_region_prefix ON public.staff_master (LOWER(region_name) text_pattern_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_zone_prefix ON public.staff_master (LOWER(zone_name) text_pattern_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_subzone_prefix ON public.staff_master (LOWER(sub_zone) text_pattern_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_territory_prefix ON public.staff_master (LOWER(dept_territory_code) text_pattern_ops);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staff_master_team_designation ON public.staff_master (UPPER(TRIM(team_name)), designation_name);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sales_data_period_position ON public.sales_data (reporting_month, fiscal_year, position_code);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_sales_data_position_period ON public.sales_data (position_code, reporting_month, fiscal_year);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_target_data_position_2026_27 ON public.target_data (position_code_2026_27);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_call_data_month_position ON public.call_data (month, position_code);
