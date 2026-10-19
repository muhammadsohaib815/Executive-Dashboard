# Dashboard summary query integration

The dashboard uses the monthly summary tables when their refresh snapshot is
complete and clean. It automatically uses the previous `sales_data` queries if
the migration is absent, any source period has not been backfilled, or a source
change has marked a period dirty.

## Query mapping

| Dashboard calculation | Summary source | Reason |
|---|---|---|
| Headline KPI cards and prior month comparison | position plus customer summaries | additive metrics come from the position grain; exact customer counts come from the customer grain |
| Employee and hierarchy performance | position summary | hierarchy scope is applied to `position_code` before aggregation |
| Product performance, SKU ranking, and discount analysis | position product summary | preserves product dimensions and hierarchy authorization |
| Customer ranking and first purchase | customer summary | preserves exact customer identity and positive sale state |
| AI employee and product analysis | position, position product, and customer summaries | uses the narrowest grain that supports each filter and exact calculation |
| Depot diagnosis | `sales_data` | depot is not present in the validated summaries |
| Call activity | `call_data_rollup` | separate activity source |
| Targets | `target_data` | the table is small and its month columns already match the requested target formulas |

Single-position field-force requests and the legacy SKU endpoint retain their
indexed raw queries because measured plans were faster at those narrow scopes.

The product only summary remains available for reporting that does not need an
employee hierarchy. Dashboard queries use the position product table so a user
cannot see products outside their authorized position list.

## Refresh after data loading

The `sales_data` triggers record inserted, updated, deleted, or truncated
periods as dirty. Run this after a source load or correction and before serving
the affected period from summaries:

```powershell
python db/refresh_sales_monthly_summaries.py --dirty --expect-db <database-name> --apply
python db/validate_sales_monthly_summaries.py --expect-db <database-name>
```

Refresh runs in one transaction. Requests continue using raw queries while a
dirty marker exists, so they do not read a partial summary refresh.

## Rollback

Set `SALES_SUMMARIES_ENABLED=false` in `.env` and restart the API to switch all
integrated queries back to `sales_data` without changing response fields. To
remove the derived objects after traffic is on the raw path, run
`db/migrations/003_sales_monthly_summaries_rollback.sql` in a reviewed database
session. The rollback does not alter `sales_data` or `target_data`.

## Materialized view decision

No materialized view was added. Rankings are inexpensive after aggregation from
the position product and customer summaries, while hierarchy and filter scopes
vary per request. A materialized view for those joins would duplicate the
existing summaries or require storing authorization specific combinations.
