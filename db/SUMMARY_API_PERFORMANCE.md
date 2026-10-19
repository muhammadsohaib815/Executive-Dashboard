# Summary API validation and performance

Measured on the configured test database on 2026-10-12. The database contained
221,107 source rows across July, August, and September 2026. Measurements are
wall clock durations from identical Python calls with the 30 second API cache
bypassed.

## Result parity

| Request | Raw result vs summary result |
|---|---|
| HOD, combined, August, net sale metric | identical complete KPI response |
| ASM, FMCG, August, TP metric | identical complete KPI response |
| HOD, combined, August AI employee analysis | identical context and API analysis result |
| Selected SPO, FMCG, August | identical complete KPI response; raw route retained because it was faster |

The independent database validator also reported zero grain mismatches, zero KPI
mismatches, zero exact distinct customer mismatches, and zero source row count
mismatches for all three periods.

## Endpoint processing time

| Representative request | Raw | Summary | Improvement |
|---|---:|---:|---:|
| HOD KPI dashboard, combined, August | 4,066.5 ms | 1,645.5 ms | 2.47x |
| ASM KPI dashboard, FMCG, August | 3,625.6 ms | 1,661.4 ms | 2.18x |
| HOD AI employee analysis, combined, August | 7,048.3 ms | 3,228.5 ms | 2.18x |
| Selected SPO KPI dashboard, FMCG, August | 397.8 ms | 475.0 ms | raw retained |
| Legacy SKU endpoint, HOD, August | 345.3 ms | 1,377.4 ms | raw retained |

Durations include hierarchy resolution, target queries, call data, response
assembly, and database connection waits. They vary with cache state and current
database load.

## Read only execution plans

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` was run for the national August
headline aggregate on the test database.

| Plan | Execution | Shared hit blocks | Shared read blocks |
|---|---:|---:|---:|
| Raw `sales_data` headline | 1,813.899 ms | 9,514 | 0 |
| Position plus exact customer summaries | 580.721 ms | 1,656 | 3,627 |

This plan comparison is read only. No `EXPLAIN ANALYZE` was run against update,
delete, refresh, or migration statements.

## Installed snapshot

| Table | Rows |
|---|---:|
| `sales_monthly_position_summary` | 997 |
| `sales_monthly_product_summary` | 433 |
| `sales_monthly_customer_summary` | 150,234 |
| `sales_monthly_position_product_summary` | 10,662 |

The dirty period queue was empty after backfill and validation.
