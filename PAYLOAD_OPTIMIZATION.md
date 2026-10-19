# Dashboard payload and rendering optimization

## Response contracts

- `/api/kpis` returns only the ranking candidates required by the visible Top 10 / Bottom 10 controls. The hierarchy query keeps the exact top and bottom rows for every returned designation and for the combined view. Product achievement and discount candidates are also reduced by PostgreSQL window ranks before transfer to Python.
- `spo_sections.product_performance` is the single product-ranking array. The former `sku_performance` duplicate and the unused `team_performance` detail array are no longer serialized; `team_summary` remains unchanged.
- Manager call performance is limited to 10 rows in PostgreSQL because the panel displays 10.
- `/api/ai-insights` keeps server-side `offset` and `limit` pagination (default 20, maximum 100). Diagnostic related names are capped at 20 per finding and include `related_total` so the interface can disclose the full count without transferring thousands of names.
- Stock source rows are used internally by AI diagnosis and are not returned as a raw stock array.

## Loading and rendering

- AI analysis remains lazy: no AI analysis request is made until **Load Insights** is selected.
- Both dashboard scripts coalesce simultaneous requests with the same URL into one fetch. Failures still clear the in-flight entry and follow the existing error path.
- `window.dashboardPerformance` records KPI request, render, and total refresh time. `window.aiInsightsPerformance` records AI request and render time for browser profiling.
- FastAPI gzip compression applies to responses of at least 1,000 bytes at compression level 5.

## Measured representative responses

Measurements used `Sep-2026`, fiscal year `2026-27`, combined team, compact JSON bytes, and a local `TestClient` connected to the configured PostgreSQL database.

| Request | Before JSON | After JSON | Reduction | After gzip wire size | Before cold API | After cold API |
|---|---:|---:|---:|---:|---:|---:|
| KPI, HOD | 81,978 B | 28,710 B | 65.0% | 6,981 B | 1.85 s | 2.80 s |
| KPI, ASM | 117,709 B | 20,841 B | 82.3% | 5,430 B | 1.84 s | 3.75 s |
| AI, product, 20 cards | 1,610,900 B | 142,746 B | 91.1% | 26,766 B | 3.3-3.9 s | 6.06 s |

Cold API time is dominated by PostgreSQL work and varied under concurrent query load during these samples. The payload changes reduce serialization, transfer, parsing, and rendering work; they do not claim a database latency improvement. Cached repeat requests should be used separately when assessing the response cache.

In a fresh process, the same HOD KPI request measured 2,504 ms cold and 11.8 ms cached; the product AI request measured 3,442 ms cold and 27.0 ms cached. Both pairs returned identical response data.

The browser-exposed timing objects are the source for ongoing frontend render and total-load measurements because render time varies by browser and workstation.

A browser runtime was unavailable in the implementation environment, so an honest before/after DOM rendering number could not be captured here. Open the dashboard and inspect `window.dashboardPerformance` or `window.aiInsightsPerformance` after a load to capture request, render, and total timing on the deployment browser.

## Compatibility notes

- KPI formulas, target calculations, hierarchy authorization, filters, chart layout, and filter behavior are unchanged.
- Active field staff totals are calculated over the complete hierarchy before its response rows are reduced.
- Related AI names beyond the first 20 are represented by `related_total`; the existing disclosure shows how many of the total names were transferred.
