# Connection pool and PostgreSQL maintenance

## Inspected state

The application previously created a `ThreadedConnectionPool(1, 5)` and used a
five-slot semaphore. Every dashboard SQL call already rolled back and returned
its connection in a `finally` block. No connection leak was found in the API
query path, and no schema mutation remains in normal application startup.

The mounted incentive dashboard also had an independent, non-thread-safe
`SimpleConnectionPool(1, 5)`. When mounted in FastAPI it now shares the main
thread-safe pool, timeouts, and metrics, avoiding an extra reserved connection.
When launched as a standalone Flask process it lazily creates its own
thread-safe pool with the same configuration.

The inspected PostgreSQL instance reported:

| Item | Observed value |
|---|---:|
| `max_connections` | 100 |
| Superuser-reserved connections | 3 |
| Open server sessions | 18 |
| Sessions for this database | 5 |
| Longest open transaction during inspection | under 0.02 seconds |
| Autovacuum / statistics tracking | on / on |
| `pg_stat_statements` | not installed |

The five-connection application default is retained. It is sufficient for one
request's existing parallel query groups and leaves database capacity for
imports, maintenance, administrators, and other applications. Pool values are
per worker process: four workers with `DB_POOL_MAX=5` can open 20 application
connections.

## Application configuration

The following `.env` settings are supported:

```text
DB_POOL_MIN=1
DB_POOL_MAX=5
DB_POOL_ACQUIRE_TIMEOUT_SECONDS=5
DB_CONNECT_TIMEOUT_SECONDS=5
DB_STATEMENT_TIMEOUT_MS=15000
DB_IDLE_TRANSACTION_TIMEOUT_MS=30000
DB_KEEPALIVES_IDLE_SECONDS=30
DB_KEEPALIVES_INTERVAL_SECONDS=10
DB_KEEPALIVES_COUNT=5
```

`statement_timeout` and `idle_in_transaction_session_timeout` are applied by
libpq when each pooled session is created. TCP keepalive values are client
socket parameters. Pool acquisition now has a deadline; exhaustion returns HTTP
503 with `Retry-After: 1` instead of allowing a request to wait forever.

The application logs data-free `pool_exhausted`, `db_connection_error`, and
`db_connection_return_error` events. `/api/db-pool-stats` exposes active,
available, peak, acquisition, exhaustion, connection-error, and wait counters.
It does not expose hostnames, credentials, SQL, parameters, or customer data.
The pool closes when the FastAPI lifespan ends.

Recommended starting configurations:

| Environment | Workers | Pool min/max per worker | Maximum application sessions |
|---|---:|---:|---:|
| Local development | 1 | 1 / 5 | 5 |
| Production, modest traffic | 2 | 1 / 5 | 10 |
| Production, measured higher concurrency | 4 | 1 / 5 | 20 |

Increase workers or pool size only after pool statistics show sustained waits or
exhaustions and PostgreSQL still has capacity. Keep total application pool
capacity below the server limit after reserving connections for administrators,
maintenance, imports, and other services. For this server, 20 application
connections is a conservative initial ceiling.

## Statistics and vacuum findings

`sales_data` contained 221,107 rows and had recent automatic analyze and vacuum
timestamps. The summary tables also had recent automatic statistics. The
`call_data_rollup` estimate was 460,223 live rows with only 16 dead rows.
No table-specific autovacuum settings were present, and no vacuum was running.

`staff_master` and `target_data` contained 558 and 3,809 rows, but their
`pg_stat_user_tables` live-row estimates were zero and no analyze timestamp was
recorded. Run explicit `ANALYZE` after imports so hierarchy and target join
plans do not wait for an autovacuum threshold. Current dead-row counts do not
justify a manual vacuum.

## Safe post-import procedure

1. Commit the CSV import. Never keep the import transaction open while users
   wait for dashboard queries.
2. Refresh the call-data rollup if call data was replaced or its source table
   was recreated.
3. Refresh dirty monthly summaries. Use a full summary refresh after a source
   table replacement or an import that bypassed triggers.
4. Review the maintenance plan:

   ```text
   python db/post_import_maintenance.py --expect-db <database-name>
   ```

5. Apply statistics maintenance:

   ```text
   python db/post_import_maintenance.py --expect-db <database-name> --apply
   ```

6. Validate summary data and monitor `/api/db-pool-stats`, slow-query logs, and
   summary freshness.

The default maintenance mode runs `ANALYZE`, which takes a lightweight read lock
and permits normal reads and writes. The script has a five-second lock timeout
and a 30-minute statement timeout. It is plan-only unless `--apply` is supplied,
and it requires the exact database name.

After a delete-heavy correction or bulk replacement, schedule the following in
a lower-traffic window:

```text
python db/post_import_maintenance.py --mode vacuum-analyze --expect-db <database-name> --apply
```

Regular `VACUUM (ANALYZE)` does not take the exclusive lock used by `VACUUM
FULL`, but it consumes I/O and CPU. Do not run `VACUUM FULL` on live dashboard
tables during normal service. Autovacuum should remain enabled.

## Administrator-reviewed improvements

These changes require database administrator review and were not applied:

- Install and preload `pg_stat_statements` to measure normalized execution
  counts and total query time. This can require changing
  `shared_preload_libraries` and restarting PostgreSQL before running `CREATE
  EXTENSION pg_stat_statements`.
- Configure production alerting for nonzero pool exhaustions or connection
  errors, repeated HTTP 503 responses, transactions open longer than 30
  seconds, summary refresh failures, and stale analyze timestamps.
- Review PostgreSQL memory settings with the total worker and connection count.
  The database has written about 13.7 GB of temporary files over its statistics
  lifetime, but `work_mem` should not be increased globally without identifying
  the responsible plans because it is available per sort/hash operation and per
  connection.

## Concurrency baseline

A read-only test ran ten concurrent 200 ms PostgreSQL queries through the
five-connection application pool.

| Measurement | Before | After |
|---|---:|---:|
| Wall time | 749.5 ms | 832.2 ms |
| Median request time | 528.6 ms | 606.2 ms |
| Maximum request time | 742.7 ms | 819.8 ms |
| Peak pooled connections | not previously recorded | 5 |
| Exhaustions / connection errors | not previously recorded | 0 / 0 |

The maximum connection count intentionally stayed at five, so throughput is
unchanged by design. The small timing difference includes connection creation
and local database load. The improvement is bounded waiting, observable
contention, session timeouts, and predictable failure behavior rather than a
blind increase in database concurrency.

A separate HTTP-level run issued ten simultaneous `/api/meta` requests. All ten
returned HTTP 200 in 2.01 seconds total; median response time was 1.98 seconds.
The pool reached five active connections, recorded no exhaustion and no
connection error, and returned to zero active connections afterward. Maximum
observed slot wait was 1.54 seconds, which confirms measurable contention but
remains below the five-second acquisition deadline. This workload does not
justify increasing the connection limit without broader production traffic
measurements.
