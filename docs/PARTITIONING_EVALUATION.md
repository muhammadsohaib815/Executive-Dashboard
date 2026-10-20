# `sales_data` partitioning evaluation

## Decision

Do not partition the production table at its current size. The inspected table
has 221,107 rows and occupies about 230 MB including 3.4 MB of indexes. Monthly
summary tables already serve the expensive dashboard aggregates, selective
single-position requests use indexes on the raw table, and current pool tests
showed no exhaustion.

Re-evaluate partitioning when one or more of these conditions is sustained:

- raw `sales_data` exceeds roughly 5 million rows or several fiscal years;
- raw monthly queries remain material after summary routing and scan millions
  of rows despite suitable indexes;
- retention or bulk month replacement needs partition detach/drop semantics;
- measured primary database I/O, CPU, or maintenance time becomes a limiting
  resource.

## Current growth and date quality

| Fiscal period | Rows | Share of table | Positions | Products | Customers |
|---|---:|---:|---:|---:|---:|
| July 2026 | 74,396 | 33.6% | 294 | 87 | 30,118 |
| August 2026 | 75,205 | 34.0% | 290 | 87 | 30,413 |
| September 2026 | 71,506 | 32.3% | 298 | 89 | 28,658 |

The observed average is about 73,700 rows per month. At the same rate, one full
year would contain about 884,000 rows and three years about 2.65 million rows.
Only three periods are present, so this is a projection rather than a measured
long-term growth rate.

`reporting_month` and `fiscal_year` are text. A real `transaction_date date`
column already exists. It was non-null on every row, and all 221,107 rows mapped
to the same calendar month as `reporting_month`. Each reporting month contained
exactly one transaction calendar month. A new normalized date column is not
needed if future partitioning uses `transaction_date`.

## Pruning estimate

With the current three months, a monthly transaction-date partition could
exclude about 66% to 68% of heap rows for a one-month query. At the projected
one-year size it could exclude about 92%, and at three years about 97%.
Fiscal-year partitioning provides no pruning today because every row belongs to
`2026-27`; at three equally sized fiscal years it would exclude about 67%.

These estimates describe heap elimination, not end-to-end speed. Existing API
SQL filters on the text `reporting_month` and would not prune partitions keyed
by `transaction_date` until each query also supplies a matching half-open date
range. Summary routing already reduces current raw work more cheaply.

## Operational risks

- PostgreSQL cannot convert this ordinary table to a partitioned table in
  place. Migration requires a second table, a full copy, validation, and a
  short write freeze for cutover.
- The table has no primary key or unique constraint. Reliable bidirectional
  delta synchronization and rollback after accepting new writes would be
  difficult until a stable source key is defined.
- Cache-invalidation and summary-dirty triggers must be recreated on the new
  parent and verified after cutover.
- Existing indexes become partitioned parent indexes with one physical index
  per child. Index creation, validation, monitoring, and future partition
  creation all become operational tasks.
- Unique constraints on a partitioned table must include the partition key.
- Query code must add `transaction_date >= month_start AND transaction_date <
  next_month` while retaining existing fiscal-year and reporting-month checks
  during rollout.
- A default partition is needed for invalid, null, or future dates, and it must
  be monitored so bad imports do not silently defeat pruning.
- Table rename cutover affects grants, triggers, dependent scripts, and import
  jobs. The inspected table currently has no constraints, inbound foreign keys,
  or row-level security policies, but those checks must be repeated immediately
  before a future migration.

## Future migration and rollback plan

The guarded, plan-only SQL skeletons are:

- [`migrations/005_sales_data_month_partition_PLAN.sql`](migrations/005_sales_data_month_partition_PLAN.sql)
- [`migrations/005_sales_data_month_partition_ROLLBACK_PLAN.sql`](migrations/005_sales_data_month_partition_ROLLBACK_PLAN.sql)

Both files raise an exception before any plan statements so migration runners
cannot apply them accidentally. Before converting them into an executable test
database migration:

1. Define and validate a stable source-row key.
2. Update all raw monthly queries to include transaction-date bounds and prove
   partition pruning with `EXPLAIN (ANALYZE, BUFFERS)`.
3. Create monthly partitions ahead of the import schedule and a monitored
   default partition.
4. Copy the source under a repeatable snapshot, validate row counts and KPI
   checksums by month, then rebuild statistics.
5. Pause imports, capture the final delta, lock briefly, recreate triggers and
   grants, rename tables, and validate again.
6. Keep the old table read-only through an observation window. Do not accept
   writes that cannot be replayed to it if immediate rename rollback is a
   requirement.

