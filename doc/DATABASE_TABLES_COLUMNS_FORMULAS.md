# Database tables: columns, formulas, and purpose

This document covers the 13 PostgreSQL tables used by the Executive Dashboard. The live schema column counts were checked on 20 October 2026. None of these columns is a PostgreSQL generated column. Original data values come from imports; summary values are calculated by refresh jobs and triggers.

## Table overview

| Table | Columns | Purpose |
|---|---:|---|
| `sales_data` | 91 | Original sales transactions and the source of sales KPIs. |
| `target_data` | 144 | Product and staff targets for FY 2026–27, with separate columns for each month. |
| `staff_master` | 33 | Employees, positions, geography, and reporting hierarchy. |
| `call_data` | 15 | Original field-force call records. |
| `call_data_rollup` | 11 | Precalculated FMCG calls by manager, shop, day, and outcome. |
| `cpd_phr_daily_stock_ledger` | 30 | Daily product and depot stock records. The current dashboard does not use this incomplete connected ledger. |
| `sales_monthly_position_summary` | 24 | Monthly sales totals per staff position. |
| `sales_monthly_product_summary` | 26 | Monthly sales totals per product and product group. |
| `sales_monthly_customer_summary` | 29 | Monthly sales per position, product, and customer; supports exact customer counts. |
| `sales_monthly_position_product_summary` | 27 | Monthly product sales per staff position. |
| `sales_monthly_summary_dirty_period` | 4 | Months whose source sales changed and need refreshing. |
| `sales_monthly_summary_refresh_state` | 4 | Last successful refresh and source row count for each month. |
| `dashboard_cache_generation` | 3 | Version counter that invalidates cached dashboard responses after data changes. |

## Original data tables

### `sales_data` — 91 columns

Each row is a source sales record.

- **Record and load metadata:** `_id`, `vid`, `originalsuid`, `entrydate`, `systemdate`, `originalnetvaluesalemonthly`, `remarks`, `_class`.
- **Customer and provider:** `sndpop`, `sndp_provider`, `18_digit_sndp`, `15_digit_pop`, `cust_mapping`, `cust_type`, `account_type`, `cust_number`, `cust_name`, `address`, `provider_code`, `provider_donor`, `provider_status`, `provider_type`, `provider_gender`, `provider_qlf`, `provider_team`, `letter`.
- **Organization and geography:** `territory`, `territory_name`, `depot`, `depot_name`, `sgp`, `grp_name`, `position_code`, `ff_territory`, `sas_code`, `designation`, `team_region`, `zone`, `sub_zone`, `team`, `sub_team`, `team_channel`, `donor`, `district`, `tehsil`, `province`, `region`, `population_pbs`, `urban`, `urban_%`, `rural`, `rural_%`, `latitude`, `longitude`.
- **Product and transaction:** `product_no`, `prd_name`, `prd_cat`, `grp`, `prd_grp`, `group_on`, `prd_size`, `price`, `transaction_date`, `invoice_no`, `batch`, `expiry`, `class`, `channel`, `booked_by`, `section_code`, `section_name`, `club_section`, `nature`, `sub_nature`, `sale_type`.
- **Stored measures:** `net_qty`, `net_value`, `bonus`, `bonus_value`, `discounts`, `foc_discount`, `e_qty`, `cyp`, `tp_sale_value`, `bonus_discount`, `mnp_commission`, `net_wo_reg_disc_value`, `net_sale_value`.
- **Reporting period:** `reporting_month`, `fiscal_year`, `cal_year`.

The dashboard sums stored measures. Their original row-level business formulas are not defined in this repository. `position_code` links sales to `staff_master`; `product_no` connects sales products to `target_data`. KPI filters use `reporting_month` and `fiscal_year`.

### `target_data` — 144 columns

Each row associates a position and product with assumptions and targets.

- **Scope and product identifiers (22):** `team`, `team_channel_26_27`, `sub_teams`, `zone`, `sub_zone`, `region`, `dept_territory_code_2026_27`, `position_code_2026_27`, `ff_name`, `base`, `emp_no`, `desg`, `sgp_grp`, `type`, `category`, `group`, `product_group`, `product_group_on_master`, `mapping`, `sas_code`, `product_no`, `prd_bu_sas`.
- **P1 assumptions (9):** `gross_tp_p1`, `reg_disc_pct_p1`, `reg_disc_p1`, `add_disc_pct_p1`, `add_disc_p1`, `reg_add_disc_p1`, `reg_add_disc_pct_p1`, `cogs_p1`, `cyps_p1`.
- **P2 assumptions (9):** `gross_tp_p2`, `reg_disc_pct_p2`, `reg_disc_p2`, `add_disc_pct_p2`, `add_disc_p2`, `reg_add_disc_p2`, `reg_add_disc_pct_p2`, `cogs_p2`, `cyps_p2`.
- **Monthly targets (96):** Each of these eight prefixes has a column for every monthly suffix listed below: `tgt_unit_`, `tgt_tp_value_`, `tgt_add_disc_value_`, `tgt_reg_disc_value_`, `tgt_net_w_reg_`, `tgt_net_wo_reg_`, `tgt_cogs_`, `tgt_cyps_`.
- **Monthly suffixes:** `jul_26`, `aug_26`, `sep_26`, `oct_26`, `nov_26`, `dec_26`, `jan_27`, `feb_27`, `mar_27`, `apr_27`, `may_27`, `jun_27`. For example, `tgt_unit_jul_26` and `tgt_unit_aug_26`.
- **YTD targets (8):** `ytd_tgt_unit_2026_27`, `ytd_tgt_tp_value_2026_27`, `ytd_tgt_add_disc_2026_27`, `ytd_tgt_reg_disc_2026_27`, `ytd_tgt_net_w_reg_2026_27`, `ytd_tgt_net_wo_reg_2026_27`, `ytd_tgt_cogs_2026_27`, `ytd_tgt_cyps_2026_27`.

The target values are imported. This repository does not define their original P1/P2, monthly, or YTD formulas. For a selected month, the dashboard sums the corresponding `tgt_*_<month>` column for authorized positions. `position_code_2026_27` is the target-side staff key.

### `staff_master` — 33 columns

`position_code`, `team_id`, `team_name`, `zone_id`, `zone_name`, `sub_zone`, `alias_zone`, `team_region_id`, `region_name`, `alias_region`, `province`, `hawk_emp_id`, `check_status`, `sas_id`, `sas_upload`, `dept_territory_code`, `employee_position_code`, `employee_name`, `base_town`, `nature_type`, `payroll_type`, `e_code`, `doj`, `desg_id`, `designation_name`, `level`, `dept_id`, `department_name`, `report_to_position_code`, `report_to_name`, `base_name`, `actual_field_force`, `remarks`.

`position_code` and `report_to_position_code` define the manager hierarchy. The dashboard follows that hierarchy and uses designation, team, region, zone, sub-zone, territory, and employee fields to determine the sales scope and populate filters.

### `call_data` — 15 columns

`team`, `position_code`, `ff_id`, `ff_name`, `month`, `call_date`, `manager`, `base_town`, `customer_name`, `ww`, `call_type`, `order`, `rejection`, `total_sum_of_calls`, `geometer_range`.

These are imported call details. The rollup counts source rows and classifies `order`; its `calls` field does not sum `total_sum_of_calls`.

### `cpd_phr_daily_stock_ledger` — 30 columns

`stock_date`, `stock_month`, `stock_fiscal_year`, `depot_id`, `depot_name`, `product_no`, `prd_name`, `prd_cat`, `grp`, `grp_name`, `prd_grp`, `group_on`, `team`, `team_region`, `zone`, `sub_zone`, `open_stock`, `receipts`, `transfer`, `sales_unit`, `bonus`, `closing_unit`, `closing_value`, `transits`, `total_stock_pck`, `total_stock_e_qty`, `total_stock_value`, `avg_sale`, `inv_days`, `muid`.

This table describes stock by date, depot, and product. The dashboard currently excludes it because the connected data is incomplete. The source formulas for fields such as `closing_unit`, `avg_sale`, and `inv_days` are not present in this repository.

## Calculated monthly sales summaries

All four `sales_monthly_*_summary` tables have these **20 common measure columns**, calculated within each table's grouping from `sales_data`:

| Column | Refresh formula |
|---|---|
| `transaction_count` | `COUNT(*)` |
| `gross_tp_value` | `SUM(tp_sale_value)` |
| `net_sale_value` | `SUM(net_sale_value)` |
| `net_wo_reg_disc_value` | `SUM(net_wo_reg_disc_value)` |
| `units` | `SUM(e_qty)` |
| `net_qty` | `SUM(net_qty)` |
| `cyp` | `SUM(cyp)` |
| `discounts` | `SUM(discounts)` |
| `bonus_discount` | `SUM(bonus_discount)` |
| `mnp_commission` | `SUM(mnp_commission)` |
| `net_value` | `SUM(net_value)` |
| `positive_net_sale_value` | `SUM(net_sale_value)` for rows where `COALESCE(net_sale_value, 0) > 0` |
| `positive_tp_sale_value` | `SUM(tp_sale_value)` for rows where `COALESCE(tp_sale_value, 0) > 0` |
| `negative_net_sale_abs` | `SUM(ABS(net_sale_value))` for rows where `COALESCE(net_sale_value, 0) < 0` |
| `return_impact_value` | Sum of `ABS(net_sale_value)` where `net_sale_value < 0 OR net_qty < 0 OR net_value < 0`; other rows contribute zero |
| `net_sale_value_rows` | `COUNT(net_sale_value)`; excludes null values |
| `net_qty_rows` | `COUNT(net_qty)`; excludes null values |
| `positive_sale_rows` | Count of rows with `COALESCE(net_sale_value, 0) > 0` |
| `active_customer_count` | Distinct `cust_number` on rows with positive net sale |
| `transacting_customer_count` | Distinct non-null `cust_number` |

Their other columns define one row's grain:

| Table | Other columns and grain |
|---|---|
| `sales_monthly_position_summary` | `reporting_month`, `fiscal_year`, `team`, `position_code`: one row per month/team/position. |
| `sales_monthly_product_summary` | `reporting_month`, `fiscal_year`, `team`, `product_no`, `group_on`, `prd_name`: one row per month/team/product/group; `prd_name = MAX(prd_name)`. |
| `sales_monthly_customer_summary` | `reporting_month`, `fiscal_year`, `team`, `position_code`, `product_no`, `group_on`, `cust_number`, `cust_name`, `has_positive_sale`: one row per month/team/position/product/group/customer; `has_positive_sale = BOOL_OR(COALESCE(net_sale_value, 0) > 0)`. |
| `sales_monthly_position_product_summary` | `reporting_month`, `fiscal_year`, `team`, `position_code`, `product_no`, `group_on`, `prd_name`: one row per month/team/position/product/group; `prd_name = MAX(prd_name)`. |

These formulas are implemented in [`db/refresh_sales_monthly_summaries.py`](../db/refresh_sales_monthly_summaries.py). The same customer may occur in multiple products or positions, so **do not sum customer counts across summary rows**. For an exact count across a selected scope, count distinct customers from `sales_monthly_customer_summary`.

## Call rollup

### `call_data_rollup` — 11 columns

`kind`, `month`, `position_code`, `manager`, `ff_name`, `customer_name`, `call_date`, `calls`, `accepted`, `rejected`, `shop_closed`.

| `kind` | Grouping and formula |
|---|---|
| `manager_day` | Month, position, manager, field-force name, call date; `calls = COUNT(*)`. |
| `shop_month` | Month, position, customer; `calls = COUNT(*)`. |
| `shop_day` | Month, position, customer, call date; `calls = COUNT(*)`. |
| `outcome` | Month and position; `calls = COUNT(*)`. `accepted`, `rejected`, and `shop_closed` count rows whose trimmed, uppercase `order` is `ACCEPTED`, `REJECTED`, or `SHOPCLOSED`, respectively. |

Only FMCG source rows with a non-null month and position enter this rollup. Triggers adjust its counts when `call_data` changes. The definitions are in [`db/call_data_rollup.sql`](../db/call_data_rollup.sql) and [`db/call_data_rollup_triggers.sql`](../db/call_data_rollup_triggers.sql).

## Refresh and cache control tables

### `sales_monthly_summary_dirty_period` — 4 columns

`reporting_month`, `fiscal_year`, `revision`, `changed_at`. A sales insert, update, delete, or truncate marks affected periods. `revision` increases on subsequent changes; `changed_at` records the latest mark. The refresh job uses this table to choose which months to rebuild.

### `sales_monthly_summary_refresh_state` — 4 columns

`reporting_month`, `fiscal_year`, `source_rows`, `refreshed_at`. After rebuilding a month, the job records its source sales row count and refresh time. The dashboard checks the refresh state and dirty markers before using summaries; otherwise it queries raw sales.

### `dashboard_cache_generation` — 3 columns

`singleton`, `generation`, `changed_at`. This table has one row. Data-change triggers increment `generation` and update `changed_at`, so API workers discard stale cached responses. See [`db/migrations/004_dashboard_cache_invalidation.sql`](../db/migrations/004_dashboard_cache_invalidation.sql).

## Main dashboard KPI formulas

For the selected reporting month and authorized staff positions:

| KPI | Formula |
|---|---|
| Achievement % | `actual / target * 100`; absent when the target is zero. |
| Target gap | `target - actual`. |
| Actual discount | Total `tp_sale_value - net_sale_value`. |
| Discount % | Actual discount divided by total TP, times 100. |
| Discount budget | Monthly additional-discount target plus regular-discount target. |
| Active shops | Distinct customers with a positive net sale. |
| Active staff | Distinct positions with a positive net sale. |
| Returns | Sum of absolute negative `net_sale_value`. |
| Return % | Returns divided by positive TP value, times 100. |
| Average sales per productive shop | Selected sales metric divided by active shops. |
| Month growth | `(current selected metric - previous month's metric) / ABS(previous month's metric) * 100`. |

The API parameter `value_metric="net_with_reg"` currently selects `net_wo_reg_disc_value` and target `tgt_net_wo_reg_*`, despite the parameter name. The exact KPI mappings and response calculations are in [`server.py`](../server.py).

## Related source

- [`DATABASE_TABLE_COLUMN_USAGE.md`](../DATABASE_TABLE_COLUMN_USAGE.md): prior schema inventory and usage analysis.
- [`db/migrations/003_sales_monthly_summaries.sql`](../db/migrations/003_sales_monthly_summaries.sql): summary and refresh-control table definitions.
- [`db/refresh_sales_monthly_summaries.py`](../db/refresh_sales_monthly_summaries.py): summary formulas and refresh process.
- [`server.py`](../server.py): dashboard query and KPI formulas.
