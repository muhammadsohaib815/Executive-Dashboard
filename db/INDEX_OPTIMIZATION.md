# Dashboard index migration

The API no longer creates indexes when `server.py` is imported. Apply the
baseline migration before starting a fresh database, then apply the two new
sales indexes after review. Existing databases already have the 20 baseline
indexes; migration 001 checks them and creates only missing ones. Neither
migration drops an existing index.

## Findings

The current database has about 221,000 sales rows, 3,800 target rows, and 558
staff rows. Existing sales indexes start with `(reporting_month, fiscal_year,
position_code)` and `(position_code, reporting_month, fiscal_year)`. The AI
product-name lookup filters on `product_no` and `reporting_month`, so neither
index can efficiently seek by product. The first-buyer query uses a positive
sales predicate and groups customer/month within staff positions. The new
partial index matches its existing `COALESCE(net_sale_value, 0) > 0` predicate.

These two indexes were tested on session-local copies of the relevant sales
columns. The copies contained all 221,107 sales rows, and the existing sales
indexes were recreated for the first-buyer comparison. No production table or
index was changed by the tests.

| Query on temporary copy | Before | After | Result |
| --- | ---: | ---: | --- |
| Product-name lookup, one product | 55.28 ms, sequential scan | 2.90 ms, new index | Same rows |
| Product-name lookup, 37 products | 107.58 ms, sequential scan | 55.62 ms, new index | Same rows |
| FMCG first-buyer count | 2,366.81 ms, existing position/period index | 1,505.74 ms, new partial index without included columns | 20,811 both times |

These are individual `EXPLAIN (ANALYZE, BUFFERS)` runs, not a production
latency guarantee. Repeat them on a full-size test database before production
rollout, and compare execution time, buffers, plan nodes, and query results.

No additional index is proposed for `target_data` or `staff_master`: the former
already has a position-code index and is small; the latter is under 1,000 rows
and its hierarchy, designation, and geography indexes already exist. The call
rollup has four used partial unique indexes. `group_on` is grouped but not
selectively filtered in the main KPI queries, and `cust_number` is grouped or
counted rather than searched by a standalone equality predicate. The existing
period/position indexes handle the common fiscal-year and staff-scope filters.
The current negative-sales checks occur inside aggregates rather than a `WHERE`
clause, so a `net_sale_value < 0` partial index would not serve those plans.
Positive sales make up 173,896 of 221,107 rows; the positive partial index is
useful because it covers the first-buyer grouping keys, not because its
predicate is highly selective. Existing low-use indexes are retained.

## Review and apply

Use a test database environment file first. The runner prints index names in
plan mode without connecting or making changes:

```powershell
python db/run_index_migration.py --migration 001 --env-file .env.test --expect-db your_test_db
python db/run_index_migration.py --migration 002 --env-file .env.test --expect-db your_test_db
```

After reviewing the plan and connection target, apply each migration:

```powershell
python db/run_index_migration.py --migration 001 --env-file .env.test --expect-db your_test_db --apply
python db/run_index_migration.py --migration 002 --env-file .env.test --expect-db your_test_db --apply
```

The runner sets `autocommit=True` and executes each `CREATE INDEX CONCURRENTLY`
as its own statement outside a transaction block. It checks the exact database
name, existing index validity, and the new index definitions. It does not log
credentials. Do not use `psql --single-transaction` or wrap these SQL files in
`BEGIN`. Concurrent creation can leave an invalid index if interrupted; the
runner stops on an invalid same-name index so an operator can inspect it before
retrying. Production application remains pending review and test-database
validation.

## Rollback

Migration 002 has a separate rollback that drops only its two new indexes.
Migration 001 preserves indexes that existed before this work.

```powershell
python db/run_index_migration.py --migration 002-rollback --env-file .env.test --expect-db your_test_db --apply
```
