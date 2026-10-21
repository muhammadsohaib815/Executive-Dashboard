# Dashboard API caching

The expensive dashboard GET endpoints use a bounded in-process TTL cache:

- `/api/kpis`
- `/api/ai-insights`
- `/api/ai-insights-legacy`

`/api/cache-stats` exposes data-free hit, miss, eviction, expiration, wait,
invalidation, and error counters. It also reports current entry counts, TTL,
capacity, and the observed database generation.

## Configuration

Add any of these settings to `.env` and restart the API:

| Setting | Default | Accepted range |
|---|---:|---:|
| `DASHBOARD_CACHE_ENABLED` | `true` | boolean |
| `DASHBOARD_CACHE_TTL_SECONDS` | `600` | 300–900 seconds |
| `DASHBOARD_CACHE_MAX_ENTRIES` | `128` | 16–1,024 responses |

Values outside the supported range are clamped. The cache uses LRU eviction and
never grows beyond its configured capacity. Concurrent misses for the same key
share one calculation.

## Cache identity and authorization

Keys include endpoint and dashboard mode, designation, employee, region, zone,
subzone, territory, team, reporting month, fiscal year, value metric, AI product
filters, band, pagination, summary routing mode, and an opaque digest of the
resolved authorized position list.

The application currently has no authentication middleware or user principal.
The resolved hierarchy scope is therefore the effective authorization identity.
Two requests share a cached response only when their filters and authorized
position set match. If authentication is added later with permissions beyond the
staff hierarchy, add that principal's stable authorization identifier to the key.

## Invalidation

Install the shared generation migration:

```powershell
python -m scripts.db.install_dashboard_cache_invalidation
python -m scripts.db.install_dashboard_cache_invalidation --expect-db <database-name> --apply
```

Statement triggers increment the generation in the same transaction as changes
to `sales_data`, `target_data`, `staff_master`, `call_data`, `call_data_rollup`,
`fmcg_cust_call`, `fmcg_exception`, `pharma_provider_calls`, or
`sales_monthly_summary_refresh_state`. Every cacheable request reads this
small generation row. A new generation clears local caches before lookup, so a
committed import or refresh is not held until TTL expiry. Rolled back data changes
also roll back the generation increment.

If the generation table cannot be read, caching is bypassed and the endpoint
runs its normal PostgreSQL queries. Cache lookup and storage errors have the same
fail-open behavior.

Rollback SQL is
`db/migrations/004_dashboard_cache_invalidation_rollback.sql`. Disable caching
with `DASHBOARD_CACHE_ENABLED=false` before removing the generation objects.

## Deployment choice

The current documented launch command starts one Uvicorn process, so Redis would
add a service dependency without improving correctness. The database generation
also keeps separate in-process caches correct if a small number of workers are
introduced, though each worker will have its own hit rate and memory allocation.

Use Redis when the deployment moves to multiple hosts or enough workers that
duplicated entries materially reduce hit rate or memory efficiency. Keep the
same complete key and generation invalidation rules in that implementation.

## Measured baseline

Configured database, HOD combined August dashboard:

| Request | Response time | SQL queries |
|---|---:|---:|
| KPI cache miss | 1,612.8 ms | 19 |
| KPI cache hit | 2.1 ms | 1 generation lookup |
| AI cache miss | 3,851.5 ms | 21 |
| AI cache hit | 1.1 ms | 1 generation lookup |

The representative run produced two misses followed by two hits: 50% response
hit rate, 50% miss rate, and no evictions or errors. A same-process generation
change converted a 3.4 ms warm hit into a 2,237.4 ms recalculation, confirming
that invalidation bypassed the old entry.
