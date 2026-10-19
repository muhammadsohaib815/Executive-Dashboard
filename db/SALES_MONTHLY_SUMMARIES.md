# Monthly sales summaries

Dashboard query routing, freshness fallback, and rollback are documented in
[SUMMARY_API_INTEGRATION.md](SUMMARY_API_INTEGRATION.md).

This stage adds summary storage and refresh tooling. Dashboard and AI API SQL
still reads `sales_data`; installing the migration does not switch any endpoint.

## Source inspection and table grains

The connected PostgreSQL 18 database contained 221,107 `sales_data` rows in
July, August, and September 2026 (FY 2026-27). `reporting_month`, `fiscal_year`,
`team`, `position_code`, `product_no`, `group_on`, and `cust_number` are `text`;
sales and discount measures are `numeric`. Those dimensions had no NULLs in
the inspected extract. The source table occupied about 219 MB. Summary keys
still use `NULLS NOT DISTINCT` so a future import with nullable dimensions
cannot create duplicate grain rows.

| Table | One row per month, fiscal year, team, and… | Current total rows |
| --- | --- | ---: |
| `sales_monthly_position_summary` | position code | 997 |
| `sales_monthly_product_summary` | product number and product group | 433 |
| `sales_monthly_customer_summary` | position, product, product group, customer number, customer name | 150,234 |
| `sales_monthly_position_product_summary` | position, product, product group | 10,662 |

The customer grain is deliberately detailed. It supports exact customer
counts after employee hierarchy, product, and group filters, and preserves the
dashboard's customer-name grouping. A customer can occur in many summary rows.
The unique grain index on each table prevents duplicate rows, including when
one of these dimensions is NULL.

Each table stores transaction count; sums of TP, net sales, net sales without
regular discount, units, net quantity, CYP, discounts, bonus discounts,
commission, and net value; positive TP and net sales; negative net-sale
returns; the AI return-impact formula; and non-NULL/positive row counts.
Product tables retain `MAX(prd_name)`. The customer table records whether any
source transaction in the grain had positive net sales.

The stored `active_customer_count` and `transacting_customer_count` describe
**only their own grain**. Never sum them across positions or products. For a
multi-position or multi-product filter, use the customer table:

```sql
SELECT COUNT(DISTINCT cust_number)
FROM public.sales_monthly_customer_summary
WHERE reporting_month = 'August,26'
  AND fiscal_year = '2026-27'
  AND has_positive_sale
  AND position_code = ANY(ARRAY['authorized-position-1', 'authorized-position-2']);
```

Likewise, count active employees as distinct `position_code` from position
summary rows with `positive_sale_rows > 0`. Sum additive amounts from **one**
chosen grain; never join two summary tables and sum both sides of a
many-to-many match.

Negative transactions remain in net sums. `negative_net_sale_abs` matches the
current KPI return formula. `return_impact_value` matches the AI condition
that also checks negative quantity or net value. SQL `SUM` preserves NULL for
an all-NULL measure group; the stored non-NULL counts allow later API work to
retain that behavior.

## Install and backfill

Review [003_sales_monthly_summaries.sql](migrations/003_sales_monthly_summaries.sql)
and the destination database first. PostgreSQL 15 or later is required. Run
these from the project root against a reviewed database:

```text
python db/install_sales_monthly_summaries.py
python db/install_sales_monthly_summaries.py --expect-db <database-name> --apply
python db/refresh_sales_monthly_summaries.py --all --expect-db <database-name>
python db/refresh_sales_monthly_summaries.py --all --expect-db <database-name> --apply
python db/validate_sales_monthly_summaries.py --expect-db <database-name>
```

The installer and refresh command plan by default. `--apply` is required for
writes, and both verify the exact database name. Migration DDL is committed
in one transaction. The refresh uses a dedicated connection and one
repeatable-read transaction for all selected periods: it stages a consistent
source snapshot, replaces rows in all four tables, updates refresh state,
validates every grain and headline KPI, clears dirty markers, then commits.
If any step fails, the transaction rolls back and existing summaries remain.

Before installation, run a real-data preflight with **temporary tables only**:

```text
python db/preflight_sales_monthly_summaries.py --month August,26 --fy 2026-27 --expect-db <database-name>
```

The preflight rolls back its session-local data. It does not install summary
tables or triggers. On the inspected database, August's 75,205 source rows
produced 290 position, 146 product, 52,292 customer, and 3,494
position-product rows. Full-grain, headline KPI, distinct-customer scope, and
source-row comparisons all reported zero mismatches. Refresh took about 5.5
seconds and validation about 11.0 seconds in that single run.

## Incremental refresh and failures

Statement triggers queue the old and new reporting periods for inserts,
updates, and deletes. A truncate queues all previously refreshed periods.
They do not rebuild summaries during an import. Run this after each committed
sales extract or on a short schedule such as every five minutes:

```text
python db/refresh_sales_monthly_summaries.py --dirty --expect-db <database-name> --apply
```

The job rebuilds whole affected months, including corrected and deleted rows.
It does not remove historical periods. A full `--all` reconciliation is useful
after a bulk replacement or a repair that bypassed triggers. If an import
drops and recreates `sales_data`, reinstall the migration and run `--all`,
because dropping a table also removes its triggers. A failed job exits nonzero;
keep the dirty markers, investigate, and rerun. Monitor the dirty-period count
and the last `refreshed_at` in `sales_monthly_summary_refresh_state`.

Concurrent source changes during a refresh remain queued for the next run.
All four summary tables change atomically for the selected periods. When API
queries are switched in a later stage, a request that issues multiple SQL
statements should use one consistent snapshot to avoid spanning two committed
summary generations.

## Scope decisions

No daily summary is needed for the current dashboard: sales and AI queries
filter `reporting_month`, and call-day analysis uses a separate call-data
rollup. `target_data` has 3,809 rows and occupies about 3.8 MB; its existing
monthly columns are much smaller than `sales_data`, so a target summary is
deferred until query plans show a benefit. Depot-level AI breakdowns still
need raw sales rows because depot is not in these four grains.

To remove this layer, review and run
[003_sales_monthly_summaries_rollback.sql](migrations/003_sales_monthly_summaries_rollback.sql).
It removes derived tables and triggers; source sales and targets remain intact.
