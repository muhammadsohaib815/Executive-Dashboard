# Final performance and scalability report

Measured on the configured PostgreSQL database on 2026-10-13. Verification was
read-only against source data. `EXPLAIN ANALYZE` was used only for SELECT
queries. No production table was partitioned, no source record was edited, and
the maintenance script remained in plan mode.

## Executive result

The dashboard is correctly using validated monthly summaries for broad scopes,
retaining raw indexed paths for narrow scopes, bounding response payloads,
caching identical authorized requests, and returning pooled connections after
use. Current `sales_data` scale does not justify partitioning, Redis, or a read
replica. The highest remaining cost is AI context construction, followed by
exact distinct-customer work in the detailed customer summary.

## Current data scale

`sales_data` contains 221,107 rows and occupies approximately 230 MB including
indexes. It has three similarly sized months in fiscal year 2026-27:

| Period | Rows | Positions | Products | Customers |
|---|---:|---:|---:|---:|
| July 2026 | 74,396 | 294 | 87 | 30,118 |
| August 2026 | 75,205 | 290 | 87 | 30,413 |
| September 2026 | 71,506 | 298 | 89 | 28,658 |

The measured average is about 73,700 rows per month. A constant-rate projection
is about 884,000 rows after one year and 2.65 million after three years.

`reporting_month` and `fiscal_year` are text. `transaction_date` is already a
real date and is complete: zero nulls and zero reporting-month mismatches across
all source rows. Future date partitioning can use `transaction_date`; adding a
second normalized month column is unnecessary.

## Partitioning decision

Partitioning is deferred. Monthly partitions would eliminate an estimated 66%
to 68% of heap rows for one-month queries today, about 92% at a full year, and
about 97% at three years. Existing queries currently filter the text reporting
month, so transaction-date pruning would require coordinated SQL changes.
Fiscal-year partitioning provides no benefit while all rows belong to one year.

The table has no primary key, making online delta replay and post-cutover
rollback materially risky. A future migration also needs per-partition indexes,
new-partition automation, trigger recreation, import changes, validation, and a
short write freeze. The complete evaluation and guarded plans are:

- [`db/PARTITIONING_EVALUATION.md`](db/PARTITIONING_EVALUATION.md)
- [`db/migrations/005_sales_data_month_partition_PLAN.sql`](db/migrations/005_sales_data_month_partition_PLAN.sql)
- [`db/migrations/005_sales_data_month_partition_ROLLBACK_PLAN.sql`](db/migrations/005_sales_data_month_partition_ROLLBACK_PLAN.sql)

Both SQL files deliberately raise an exception before any plan statement.

## Correctness validation

### Summary equivalence

The independent validator checked all three periods and reported:

- zero grain mismatches across all four summary tables;
- zero headline KPI mismatches;
- zero exact distinct-customer mismatches by team, position, and product;
- zero source-row-count mismatches.

Fresh raw-versus-summary API comparisons were identical complete JSON results:

| Scope | Raw | Summary | Improvement |
|---|---:|---:|---:|
| HOD, combined, September, net metric | 3,336.5 ms | 1,655.8 ms | 2.02x |
| ASM, FMCG, August, TP metric | 3,446.4 ms | 1,600.4 ms | 2.15x |
| RSM, Pharma, September, units metric | 1,754.0 ms | 668.1 ms | 2.63x |

### Designations and filters

Every designation present in `staff_master` returned HTTP 200 with all required
KPI fields: ASM, ASMTE, CM, DGM, EXEC, HOD, MIO, PS, RSM, SB, SPO, SPOWS, and
TE. Cold response times ranged from 193 ms to 2,260 ms. Empty EXEC and SB sales
scopes returned valid empty panels rather than errors.

The following filter cases returned HTTP 200 and retained KPI formula parity:

- July, August, and September 2026;
- combined, FMCG, and Pharma teams;
- region, zone, subzone, territory, and an active employee;
- TP, net-with-regular-discount, units, and CYP metrics;
- fiscal year 2025-26 with no targets, which returned
  `targets_available=false` and zero/empty target-dependent results.

Actual/target achievement, discount percentage, and growth-over-last-month
formulas were independently recomputed and matched. Product Top/Bottom 10 keys
and customer Top 10 keys matched full aggregates. Bottom-customer values also
matched; three customers tied at the tenth-place value, so identities at that
boundary are nondeterministic because the SQL window ordering has no secondary
customer key.

Call panels respected their SQL limits: manager rows at most 10 and shop rows
at most 10. Product and discount candidate unions were at most 20 each.

### AI, edge cases, and authorization

AI verification covered:

- ALL employee mode: 20 returned of 287 employees, 20 products, five insights;
- HOD product mode: 20 products and five insights;
- ASM low-performance employee mode;
- a selected SPO employee scope;
- response pagination and the 20-name diagnosis-detail cap.

Observed AI cold times ranged from 673 ms for a selected SPO to 5,965 ms for
the broad HOD employee request. HOD employee mode with designation specifically
set to HOD produced no employee cards but still produced product cards and five
insights; ALL mode is the populated organization-wide employee view.

Live source data contains 47,211 negative-net-sales rows, and the returns KPI
remained identical between raw and summary results. Current sales and target
join keys had no tested nulls. Synthetic tests cover null actuals, missing
targets, empty periods, negative returns, invalid stock, and incomplete history.

Unique SPO and MIO employee names resolved to exactly one authorized position.
Selected RSM and ASM scopes exactly matched independently calculated recursive
trees, with no duplicates. An unknown employee resolved to an empty scope.

One authorization identity risk remains: employee filters use `employee_name`.
There are 16 duplicate-name groups spanning multiple positions (14 SPO, one MIO,
one RSM). A duplicate name resolves every matching position. Before adding real
authentication, bind the user principal to an immutable employee or position
identifier and include that identity in cache keys.

## Measured performance

### SQL plan and database CPU sample

Read-only September headline plans produced:

| Source | Execution | Rows read by relation scans | Buffers | Local PostgreSQL CPU sample |
|---|---:|---:|---:|---:|
| Raw `sales_data` | 327.5 ms | 71,506 | 9,024 hit | 0.297 s |
| Position + exact customer summaries | 237.5 ms | 413 + 49,759 | 5,225 read + 3 hit | 0.172 s |

The summary reduced measured execution by 27.5%, relation rows by 29.8%, and
the local PostgreSQL process CPU sample by 42.1%. Buffer cache state differed,
so these are representative measurements rather than a production guarantee.
An earlier cold-buffer test recorded 1,813.9 ms raw versus 580.7 ms summary.

### API, cache, and concurrency

Six simultaneous identical cold HOD requests all returned HTTP 200 with
identical results in 1,972 ms wall time. Single-flight caching performed one
calculation and recorded five waiters. The next warm request completed in 7.6
ms. Pool peak was five connections, then returned to zero, with no exhaustion
or connection error.

The synthetic sample reported a 50% hit rate because it intentionally issued
six simultaneous misses followed by cache reads. Hit rate is workload-dependent
and should be monitored in production through `/api/cache-stats`.

All six live cache-generation triggers are enabled. The generation row was at
3, and the summary dirty queue was empty. Unit tests confirm generation changes
clear cache entries and rolled-back source writes do not invalidate committed
cache state. Source records were not changed merely to repeat that live test.

### Response transfer

| Response | Before | Final JSON | Reduction | Final gzip wire size |
|---|---:|---:|---:|---:|
| HOD KPI | 81,978 B | 28,710 B | 65.0% | 6,981 B |
| ASM KPI | 117,709 B | 20,841 B | 82.3% | 5,430 B |
| Product AI, 20 cards | 1,610,900 B | 142,746 B | 91.1% | 26,766 B |

Browser DOM and total dashboard-load comparisons could not be captured because
no browser runtime was available in the verification environment. The deployed
browser can read `window.dashboardPerformance` and
`window.aiInsightsPerformance`. No unsupported render-time claim is made.

## Infrastructure decisions

### Redis

Redis is not justified for the documented single-process deployment. The
bounded in-process cache provides 7–27 ms warm API responses, and database
generation triggers maintain correctness. Reconsider Redis for multiple hosts
or enough workers that duplicate caches materially reduce hit rate or consume
significant memory.

### Read replica

A read replica is not justified at 221,107 source rows, five pooled connections,
and zero observed pool exhaustion. It would add summary/cache freshness lag and
operational complexity. Reconsider only after sustained primary read CPU or I/O
pressure is measured and replica lag is acceptable for dashboard data.

### PostgreSQL tuning

Keep explicit post-import `ANALYZE`, autovacuum, the five-connection-per-worker
limit, and current session timeouts. Administrator review is justified for
installing `pg_stat_statements`; it is currently absent and is needed for
reliable long-term execution counts and database CPU attribution. Do not raise
global `work_mem`, connection counts, or other memory settings without measured
plans. Historical database statistics show substantial temporary-file bytes,
but they do not identify the responsible query.

## Remaining bottlenecks and risks

1. Broad AI requests remain the slowest API work at 3.2–6.0 seconds because
   several context queries still read large raw depot/customer datasets.
2. Exact customer analysis reads about 49,759 September summary rows nationally.
3. Duplicate employee names are not a safe authenticated authorization identity.
4. Customer ranking ties lack a deterministic secondary ordering key.
5. `reporting_month` remains text; partition pruning by `transaction_date`
   would require coordinated query predicates.
6. Cache is process-local and duplicates entries across workers.
7. `pg_stat_statements` is unavailable, limiting long-term execution-count and
   CPU analysis.
8. The 15-second statement timeout should be watched as data grows because
   broad AI work has the least headroom.
9. The mounted WSGI adapter emits a Starlette deprecation warning and should be
   replaced in a separate compatibility change.

## Implemented optimization inventory

- reusable SQL and endpoint performance monitoring;
- early-filtered CTEs and request-scoped hierarchy resolution;
- index migrations separated from application startup;
- monthly position, product, customer, and position-product summaries;
- atomic dirty-period refresh and independent summary validation;
- summary-backed KPI and AI paths with measured raw fallbacks;
- bounded TTL response caching with database generation invalidation;
- SQL Top/Bottom ranking limits, response pagination, gzip, lazy AI loading,
  and frontend request coalescing;
- configurable thread-safe connection pooling, acquisition deadline, session
  timeouts, keepalives, metrics, and a shared incentive-dashboard pool;
- guarded post-import ANALYZE/VACUUM procedure;
- deferred, rollback-ready partitioning plan.

## Migration and rollback inventory

| Artifact | State | Rollback |
|---|---|---|
| `001_existing_dashboard_indexes.sql` | baseline migration | preserves pre-existing indexes |
| `002_sales_query_indexes.sql` | review/apply migration; its two proposed sales indexes were not present in the final catalog | `002_sales_query_indexes_rollback.sql` |
| `003_sales_monthly_summaries.sql` | installed and validated | disable `SALES_SUMMARIES_ENABLED`, then run `003_sales_monthly_summaries_rollback.sql` |
| `004_dashboard_cache_invalidation.sql` | installed; six triggers enabled | disable caching, then run `004_dashboard_cache_invalidation_rollback.sql` |
| `005_sales_data_month_partition_PLAN.sql` | guarded plan only; not applied | guarded `005_sales_data_month_partition_ROLLBACK_PLAN.sql` |

For application rollback, deploy the prior reviewed application build. Database
objects should be rolled back only after switching API traffic away from them.
Source `sales_data` and `target_data` remain intact. The partition plan requires
no rollback because it was not executed.

## Verification result

- 71 Python tests passed.
- The frontend Node test passed.
- The independent summary validator passed all three periods with zero
  mismatches.
- Live API designation, filter, AI, concurrency, hierarchy, cache-trigger, and
  read-only SQL-plan checks completed as documented above.

## Files involved in the performance work

Core runtime: `scripts/server.py`, `scripts/performance_monitor.py`, `scripts/response_cache.py`,
`frontend/js/api.js`, and `frontend/js/ai-insights.js`.

AI and query layer: `scripts/services/ai_analysis/repository.py`,
`scripts/services/ai_analysis/engine.py`, `scripts/services/ai_analysis/diagnosis.py`, and
`scripts/services/ai_analysis/product_diagnosis.py`.

Database artifacts: the SQL migrations under `db/migrations`, summary install,
refresh and validation scripts under `scripts/db/`, and the
operational documents under `db`.

Verification: all files under `tests`, including hierarchy, summaries, cache,
pooling, payload, indexes, performance logging, and AI edge-case coverage.
