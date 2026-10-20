# Database tables, columns, and application usage

This is a read-only inventory of the PostgreSQL `public` schema used by the
dashboard.  The schema was inspected from `information_schema.columns` on 13
October 2026. The mapping below is based on the SQL in `scripts/server.py`,
`scripts/services/ai_analysis/repository.py`, the incentive data loader, and the `db/`
migrations/refresh jobs.  It describes column names and code locations only;
no customer, employee, credential, or token values are included.

## Where each relation is used

| Relation | Grain/purpose | Main code locations and operations |
|---|---|---|
| `sales_data` | Raw sales transaction rows (221,107 rows in the inspected database) | `scripts/server.py:608-940,1389` for KPI, rankings, targets and fallback/detail queries; `scripts/services/ai_analysis/repository.py:107-154,204-208` for AI evidence; `scripts/db/refresh_sales_monthly_summaries.py:136` is the summary source. |
| `target_data` | Target/product mapping rows (3,809 rows) | `scripts/server.py:734-940,1185,1384` for target achievement and product targets; `scripts/services/ai_analysis/repository.py:52,189,207` for AI/team gaps. |
| `staff_master` | Employee and reporting hierarchy (558 rows) | `scripts/server.py:278-559,684,757,820,884,1171,1244` for scope, filter lists, joins and orphan checks; `scripts/services/ai_analysis/repository.py:68,179-180,204` for staff and recursive scope. |
| `call_data` | Raw FMCG call activity | Source for `db/call_data_rollup.sql` and its triggers; cache invalidation and index migration reference it. Dashboard reads the rollup, so raw rows are not grouped on every request. |
| `call_data_rollup` | Pre-aggregated call activity by manager/shop/day/outcome (460,223 rows) | `scripts/server.py:1090-1127` for call panels; `db/call_data_rollup.sql` creates/refreshes it; `db/call_data_rollup_triggers.sql` keeps it current. |
| `cpd_phr_daily_stock_ledger` | Daily inventory/stock ledger | Present in the schema but intentionally not queried by current dashboard/AI paths because the connected data is incomplete; see `scripts/services/ai_analysis/repository.py:156-164`. |
| `sales_monthly_position_summary` | Monthly aggregate at `(month, fiscal year, team, position)` | `scripts/services/ai_analysis/repository.py` when `use_summaries=True`; maintained by `scripts/db/refresh_sales_monthly_summaries.py`; API summary routing docs in `SUMMARY_API_INTEGRATION.md`. |
| `sales_monthly_product_summary` | Monthly aggregate at `(month, fiscal year, team, product, group)` | Same summary refresh job and product-ranking/summary paths. |
| `sales_monthly_customer_summary` | Monthly aggregate at `(month, fiscal year, team, position, product, group, customer)` | AI/customer evidence and exact customer-level distinctness paths when summaries are enabled. |
| `sales_monthly_position_product_summary` | Monthly aggregate at `(month, fiscal year, team, position, product, group)` | Employee/product summaries and AI context when summaries are enabled. |
| `sales_monthly_summary_refresh_state` | Last atomic refresh and source-row count per period | `scripts/db/refresh_sales_monthly_summaries.py:152-170` and dirty-period preflight. |
| `sales_monthly_summary_dirty_period` | Periods changed by source insert/update/delete/truncate triggers | `db/migrations/003_sales_monthly_summaries.sql:170-230`; consumed by `refresh_sales_monthly_summaries.py --dirty`. |
| `dashboard_cache_generation` | Singleton cache generation/version | `db/migrations/004_dashboard_cache_invalidation.sql`; bumped by data-change triggers and read by `response_cache.py`. |
| `v_dim_position` (view) | Normalized staff dimension (`position_code`, employee, designation, geography, manager, active flag) | Defined from `staff_master`; available for reporting queries. Current endpoint scope CTEs still read `staff_master` directly to preserve existing authorization semantics. |

## `sales_data` columns (91)

**Identity/load metadata:** `_id`, `vid`, `originalsuid`, `entrydate`,
`systemdate`, `originalnetvaluesalemonthly`, `remarks`, `_class`.

**Customer/provider:** `sndpop`, `sndp_provider`, `18_digit_sndp`,
`15_digit_pop`, `cust_mapping`, `cust_type`, `account_type`, `cust_number`,
`cust_name`, `address`, `provider_code`, `provider_donor`, `provider_status`,
`provider_type`, `provider_gender`, `provider_qlf`, `provider_team`, `letter`.

**Geography/organization:** `territory`, `territory_name`, `depot`,
`depot_name`, `sgp`, `grp_name`, `position_code`, `ff_territory`, `sas_code`,
`designation`, `team_region`, `zone`, `sub_zone`, `team`, `sub_team`,
`team_channel`, `donor`, `district`, `tehsil`, `province`, `region`,
`population_pbs`, `urban`, `urban_%`, `rural`, `rural_%`, `latitude`,
`longitude`.

**Product/transaction:** `product_no`, `prd_name`, `prd_cat`, `grp`, `prd_grp`,
`group_on`, `prd_size`, `price`, `transaction_date`, `invoice_no`, `batch`,
`expiry`, `class`, `channel`, `booked_by`, `section_code`, `section_name`,
`club_section`, `nature`, `sub_nature`, `sale_type`.

**Measures:** `net_qty`, `net_value`, `bonus`, `bonus_value`, `discounts`,
`foc_discount`, `e_qty`, `cyp`, `tp_sale_value`, `bonus_discount`,
`mnp_commission`, `net_wo_reg_disc_value`, `net_sale_value`.

**Period fields:** `reporting_month`, `fiscal_year`, `cal_year`.

**Actively referenced by dashboard/AI/summary SQL:** period fields; organization
fields `position_code`, `team`, `zone`, `sub_zone`, `team_region`, `territory`,
`territory_name`, `depot_name`; product fields `product_no`, `prd_name`,
`group_on`; customer fields `cust_number`, `cust_name`; and all ten monetary/
quantity measures used by the summary job (`tp_sale_value`, `net_sale_value`,
`net_wo_reg_disc_value`, `e_qty`, `net_qty`, `cyp`, `discounts`,
`bonus_discount`, `mnp_commission`, `net_value`). `depot`/`depot_name` are used
by optional AI depot evidence. `transaction_date` is retained for source
semantics and partition evaluation, but current KPI filters use the text
period columns.

**Projection note:** The current FastAPI dashboard uses explicit column lists
from `scripts/server.py` and `scripts/services/ai_analysis/repository.py`.
Historical incentive-loader references are retained only as background context;
that loader is not part of the current runtime tree.

## `target_data` columns (144)

**Scope and joins:** `team`, `team_channel_26_27`, `sub_teams`, `zone`,
`sub_zone`, `region`, `dept_territory_code_2026_27`,
`position_code_2026_27`, `ff_name`, `base`, `emp_no`, `desg`, `sgp_grp`,
`type`, `category`, `group`, `product_group`, `product_group_on_master`,
`mapping`, `sas_code`, `product_no`, `prd_bu_sas`.

**Product-period assumptions:** `gross_tp_p1`, `reg_disc_pct_p1`,
`reg_disc_p1`, `add_disc_pct_p1`, `add_disc_p1`, `reg_add_disc_p1`,
`reg_add_disc_pct_p1`, `cogs_p1`, `cyps_p1`; the corresponding `*_p2` fields
(`gross_tp_p2`, `reg_disc_pct_p2`, `reg_disc_p2`, `add_disc_pct_p2`,
`add_disc_p2`, `reg_add_disc_p2`, `reg_add_disc_pct_p2`, `cogs_p2`,
`cyps_p2`).

**Monthly unit targets:** `tgt_unit_jul_26` through `tgt_unit_jun_27`, plus
`ytd_tgt_unit_2026_27`.

**Monthly TP targets:** `tgt_tp_value_jul_26` through `tgt_tp_value_jun_27`,
plus `ytd_tgt_tp_value_2026_27`.

**Monthly additional-discount targets:** `tgt_add_disc_value_jul_26` through
`tgt_add_disc_value_jun_27`, plus `ytd_tgt_add_disc_2026_27`.

**Monthly regular-discount targets:** `tgt_reg_disc_value_jul_26` through
`tgt_reg_disc_value_jun_27`, plus `ytd_tgt_reg_disc_2026_27`.

**Monthly net-with-regular-discount targets:** `tgt_net_w_reg_jul_26` through
`tgt_net_w_reg_jun_27`, plus `ytd_tgt_net_w_reg_2026_27`.

**Monthly net-without-regular-discount targets:** `tgt_net_wo_reg_jul_26`
through `tgt_net_wo_reg_jun_27`, plus `ytd_tgt_net_wo_reg_2026_27`.

**Monthly COGS targets:** `tgt_cogs_jul_26` through `tgt_cogs_jun_27`, plus
`ytd_tgt_cogs_2026_27`.

**Monthly CYP targets:** `tgt_cyps_jul_26` through `tgt_cyps_jun_27`, plus
`ytd_tgt_cyps_2026_27`.

`scripts/server.py` and `scripts/services/ai_analysis/repository.py` dynamically select the
month-specific `tgt_*_<mon>_<yy>` fields after checking that the column exists;
the loader uses `SELECT *` and `_rename_target_columns`, so all 144 columns
are selected only when required by the dashboard query.

## `staff_master` columns (33)

`position_code`, `team_id`, `team_name`, `zone_id`, `zone_name`, `sub_zone`,
`alias_zone`, `team_region_id`, `region_name`, `alias_region`, `province`,
`hawk_emp_id`, `check_status`, `sas_id`, `sas_upload`,
`dept_territory_code`, `employee_position_code`, `employee_name`, `base_town`,
`nature_type`, `payroll_type`, `e_code`, `doj`, `desg_id`, `designation_name`,
`level`, `dept_id`, `department_name`, `report_to_position_code`,
`report_to_name`, `base_name`, `actual_field_force`, `remarks`.

Authorization/filter SQL uses `position_code`, `employee_name`,
`designation_name`, `report_to_position_code`, `team_name`, `region_name`,
`zone_name`, `sub_zone`, and `dept_territory_code`. `v_dim_position` derives
normalized reporting fields and `is_active` from these columns. Remaining
columns are loaded by the incentive `SELECT *` and retained as staff master
attributes, but are not part of the dashboard scope predicates.

## Call and operational tables

* **`call_data` (15):** `team`, `position_code`, `ff_id`, `ff_name`, `month`,
  `call_date`, `manager`, `base_town`, `customer_name`, `ww`, `call_type`,
  `order`, `rejection`, `total_sum_of_calls`, `geometer_range`. The rollup
  procedure groups by month/position/manager/FF/customer/date and classifies
  `order` as accepted, rejected, or shop-closed.
* **`call_data_rollup` (11):** `kind`, `month`, `position_code`, `manager`,
  `ff_name`, `customer_name`, `call_date`, `calls`, `accepted`, `rejected`,
  `shop_closed`. `scripts/server.py:1090-1127` selects only the fields needed by the
  call panels.
* **`cpd_phr_daily_stock_ledger` (30):** `stock_date`, `stock_month`,
  `stock_fiscal_year`, `depot_id`, `depot_name`, `product_no`, `prd_name`,
  `prd_cat`, `grp`, `grp_name`, `prd_grp`, `group_on`, `team`, `team_region`,
  `zone`, `sub_zone`, `open_stock`, `receipts`, `transfer`, `sales_unit`,
  `bonus`, `closing_unit`, `closing_value`, `transits`, `total_stock_pck`,
  `total_stock_e_qty`, `total_stock_value`, `avg_sale`, `inv_days`, `muid`.
  It is currently excluded from API/AI calculations because the inspected
  ledger is incomplete.

## Summary, state, and view columns

All four monthly summary tables have period/team dimensions plus additive
metrics: `transaction_count`, `gross_tp_value`, `net_sale_value`,
`net_wo_reg_disc_value`, `units`, `net_qty`, `cyp`, `discounts`,
`bonus_discount`, `mnp_commission`, `net_value`,
`positive_net_sale_value`, `positive_tp_sale_value`, `negative_net_sale_abs`,
`return_impact_value`, `net_sale_value_rows`, `net_qty_rows`,
`positive_sale_rows`, `active_customer_count`, and
`transacting_customer_count`. Product summaries add `product_no`, `group_on`,
`prd_name`; customer summaries add `cust_number`, `cust_name`,
`has_positive_sale`; position summaries add `position_code`.

`sales_monthly_summary_refresh_state` has `reporting_month`, `fiscal_year`,
`source_rows`, `refreshed_at`. `sales_monthly_summary_dirty_period` has
`reporting_month`, `fiscal_year`, `revision`, `changed_at`.
`dashboard_cache_generation` has `singleton`, `generation`, `changed_at`.
The `v_dim_position` view exposes `position_code`, `employee_name`,
`designation`, `zone`, `sub_zone`, `team_region`, `city`, `reports_to`, and
`is_active`.

## Practical findings

1. Keep explicit column projections in the runtime query and service layers.
2. The FastAPI dashboard itself projects explicit columns for KPI and summary
   queries. Its raw fallback still needs the customer/product/geography fields
   listed above for rankings, AI evidence, and hierarchy filters.
3. Summary refresh intentionally projects only the 19 `SOURCE_COLUMNS` in
   `scripts/db/refresh_sales_monthly_summaries.py:50-56`, so summary tables do not
   depend on unrelated raw columns.
4. No table or source row was changed while preparing this inventory. The
   complete live schema can be reproduced with:

```sql
SELECT table_name, column_name, ordinal_position, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

## Detailed live-table analysis

The following measurements were taken with read-only `COUNT(*)`, catalog, and
statistics queries on 13 October 2026.  Table sizes are total PostgreSQL
relation sizes and include indexes where applicable.

| Relation | Exact rows | Approx. size | Assessment |
|---|---:|---:|---|
| `sales_data` | 221,107 | 230 MB | Largest transactional table. Three reporting periods are present. Dashboard filters normally use `reporting_month`, `fiscal_year`, and `position_code`; product/customer/metric columns are aggregated for rankings and AI evidence. |
| `target_data` | 3,809 | 3.8 MB | Small target/mapping table. Joined by `position_code_2026_27` and `product_no`; month is represented by separate target columns rather than rows. |
| `staff_master` | 558 | 0.8 MB | Authorization and hierarchy dimension. Recursive scope follows `report_to_position_code`; geography and designation filters are applied here. |
| `call_data` | 295,128 | 64.5 MB | Raw call events. The application reads the rollup for panels; this table is the source for rollup refresh/triggers. |
| `call_data_rollup` | 460,223 | 120.7 MB | Four row kinds (`manager_day`, `shop_month`, `shop_day`, `outcome`). This is larger than the source because one event contributes to multiple reporting grains. |
| `cpd_phr_daily_stock_ledger` | 5,008 | 1.4 MB | Inventory source, currently excluded from API/AI results because the connected ledger is incomplete. |
| `sales_monthly_position_summary` | 997 | 0.5 MB | Fast position KPI grain. Exact active-customer values are stored at this grain but must not be summed across overlapping positions. |
| `sales_monthly_product_summary` | 433 | 0.25 MB | Fast product/group ranking grain. |
| `sales_monthly_customer_summary` | 150,234 | 84.8 MB | Customer-level exactness grain; largest summary because it preserves customer identity and product/position dimensions. |
| `sales_monthly_position_product_summary` | 10,662 | 5.1 MB | Employee/product ranking and AI comparison grain. |
| `sales_monthly_summary_refresh_state` | 3 | 32 KB | One marker per refreshed month/fiscal-year pair; all three source periods are recorded with matching source-row counts. |
| `sales_monthly_summary_dirty_period` | 0 | 16 KB | Empty currently, so no source period is waiting for a summary refresh. |
| `dashboard_cache_generation` | 1 | 24 KB | Singleton invalidation counter. |
| `mv_targets_long` (materialized view) | 365,664 | 64.1 MB | Long-form target view with columns `position_code`, `group_on`, `metric`, `month_start`, `value`; useful for target trends and rankings. |
| `v_dim_position` (view) | derived | — | Normalized projection over `staff_master`; no stored rows or indexes. |

### Relationships and join keys

* `sales_data.position_code` is the transaction-side authorization key and is
  resolved against `staff_master.position_code`. The relationship is logical;
  the source schema does not declare a foreign key, which allows orphan sales
  rows and is why the API includes explicit orphan handling.
* `target_data.position_code_2026_27` is the target-side equivalent of the
  staff/sales position key. `target_data.product_no` joins product targets to
  sales product numbers. `product_group_on_master` is used when a target group
  filter is selected.
* Summary tables retain the source dimensions as grouped keys. They are not
  foreign-key constrained to staff or product master data so historical and
  unmapped rows can be preserved.
* `call_data_rollup` has partial unique indexes per `kind`, rather than one
  universal key, because each kind has a different grain.
* `mv_targets_long` is derived from target data and is independent of the
  sales summary tables; it should be refreshed after target imports.

### Index and statistics findings

* `sales_data` currently has two complementary indexes:
  `(reporting_month, fiscal_year, position_code)` and
  `(position_code, reporting_month, fiscal_year)`. These match the two main
  access patterns (period-first dashboard requests and hierarchy-position
  requests). Product/customer filtering is primarily served by the monthly
  summaries; adding broad raw-table indexes should be justified with `EXPLAIN`
  because the table is only 221k rows at present.
* `target_data` has an index on `position_code_2026_27`, matching the main
  authorization join. Since the table is only 3,809 rows, additional indexes
  on every target metric would add write/storage cost without an established
  benefit.
* `staff_master` has indexes for position, manager, designation/employee,
  geography, and territory. This covers recursive child lookup and filter-list
  queries. Several prefix/normalized indexes intentionally support the
  case-insensitive filter predicates.
* `call_data` has `(month, position_code)`, which matches rollup refresh and
  period/position lookup. `call_data_rollup` has four partial unique indexes
  matching its four grains plus a conditional `calls <= 0` index.
* Summary tables have unique grain indexes and lookup indexes beginning with
  `(reporting_month, fiscal_year, ...)`, matching API filters. The customer
  summary is intentionally indexed separately by position and product because
  both access paths are used.
* `mv_targets_long` currently has both `idx_mv_targets_long_lookup` and
  `idx_mv_targets_lookup` with the same key `(metric, month_start,
  position_code)`. They are duplicate indexes and should be reviewed before
  the next migration; do not drop either one without checking dependency and
  usage statistics.
* `pg_stat_user_tables.n_live_tup` returned zero for these relations in the
  inspection session, while exact counts are non-zero. This means the
  statistics estimates are stale or not populated for this connection; query
  plans and maintenance decisions should use a post-import `ANALYZE` and then
  re-check `pg_stat_user_tables`.

### Data-quality and correctness risks

1. Most source columns are nullable, including period, position, customer,
   product, and numeric measures. KPI SQL therefore uses `COALESCE` and
   preserves negative returns; replacing nullable sums with zero earlier in a
   query can change business results.
2. `reporting_month` and `fiscal_year` are text. All three loaded periods are
   `July,26`, `August,26`, and `September,26` in fiscal year `2026-27`. Text
   ordering is not chronological ordering, so date conversion must be
   explicit if a query sorts or ranges across months.
3. The monthly summary refresh state has source counts exactly matching the
   three raw periods (74,396, 75,205, and 71,506). The dirty-period table is
   empty, indicating summaries are currently caught up according to the
   trigger/refresh workflow.
4. `COUNT(DISTINCT cust_number)` remains non-additive across position, product,
   and team groups. Use the customer summary for exact scoped counts; do not
   add `active_customer_count` values from overlapping groups.
5. `call_data` and `call_data_rollup` are intentionally not joined to sales
   transactions in KPI queries. Joining them at raw-event grain would multiply
   sales totals.

### Priority actions from this analysis

1. Keep the current sales and hierarchy indexes, run `ANALYZE` after every
   large import, and capture representative `EXPLAIN (ANALYZE, BUFFERS)` plans.
2. Replace the incentive loader's `SELECT *` statements with reviewed column
   lists after confirming the incentive calculations' required fields.
3. Review the duplicate `mv_targets_long` lookup indexes using
   `pg_stat_user_indexes` before removing anything.
4. Keep raw `sales_data` queries for transaction-level and unsupported filters;
   route additive KPI/ranking work to the validated monthly summaries.
5. Treat `cpd_phr_daily_stock_ledger` as unavailable until its load process
   supplies complete dates and validated stock measures.

### Additional observed distributions

* `call_data_rollup` contains 9,534 `manager_day`, 501 `outcome`, 286,656
  `shop_day`, and 163,532 `shop_month` rows. These counts explain why the
  rollup is larger than `call_data` and why every query must constrain
  `kind`.
* `mv_targets_long` contains eight metrics (`units`, `tp_value`, `reg_disc`,
  `add_disc`, `net_w_reg`, `net_wo_reg`, `cogs`, and `cyp`), each with 45,708
  rows.
* The inspected `sales_data` rows have no null/blank `position_code`,
  `product_no`, `cust_number`, or period values. `target_data` has no null/blank
  position, product, or product-group mapping values. `staff_master` has one
  row with a null/blank manager (`report_to_position_code`), which is expected
  for a root employee but should be checked when validating hierarchy roots.
