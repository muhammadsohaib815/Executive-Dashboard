# Ranked performance analysis

`GET /api/ai-insights` uses the existing dashboard hierarchy, month/FY, employee,
team and geographical filters. The AI panel deliberately does not offer individual-product or product-group pickers. Its Product / SKU toggle analyses the complete currently filtered portfolio. SQL values are parameterized; monthly target identifiers are
constructed only from a parsed date and checked against the database schema.
No new tables, external AI requests or production fixture data are used.

## Structure

- `repository.py`: read-only PostgreSQL aggregation and verified column mappings.
- `engine.py`: 15 conditional analysis families and their evidence/action text.
- `insight_ranker.py`: normalized scoring and semantic deduplication.
- `../../js/ai-insights.js`: presentation, filter refresh and stale-response protection.

Priority = 35% impact + 25% severity + 20% urgency + 15% actionability + 5% confidence.
Impact is the square root of financial exposure divided by the selected scope's
sales/target baseline, capped at 100. This rewards monetary impact without letting
one large scope flatten every smaller actionable finding. Thresholds are business
rules, not measured probabilities. The materiality floor is the larger of PKR 1,000
and 1% of the scope baseline. Confidence below 60 and priority below 30 are excluded.
Manager relevance adjusts actionability. No category receives a guaranteed slot.
Only the top five distinct findings are returned; fewer are shown when justified.
Sales gap, product gap and portfolio gap share one diagnosis group. Stockout and
stock-constrained findings on the same product also share one group.

## Data semantics and limits

- Net sales: `net_sale_value`; units: `net_qty`.
- Targets: `tgt_net_w_reg_*`, `tgt_unit_*`, `tgt_tp_value_*` for FY 2026-27 only.
- Regular discount compares `discounts / tp_sale_value` with
  `tgt_reg_disc_value_* / tgt_tp_value_*`. Bonus/additional discount compares
  `bonus_discount` with `tgt_add_disc_value_*` using the same TP denominators.
  Discount types compete within the same insight family and are not added together.
- Return lines have negative `net_sale_value`, `net_qty` or `net_value`; their
  exposure uses absolute `net_sale_value` once per line. Rate denominator is
  positive net sales, not net-after-return sales.
- Trends require at least three consecutive completed months. Missing months are
  not zero-filled; incomplete/future periods are not compared with full months.
  Current-period gaps explicitly refer to full-month targets. A period without
  loaded sales data produces an unavailable message, not a zero-sales warning.
- Inventory uses the latest snapshot per depot/product within the selected month.
  Depot names and product codes must match actual sales in the selected scope.
  Stock is shared depot evidence, never employee-owned availability. Coverage is
  evaluated per depot; inventory-day averages are not combined across depots.
  Recovery is a conditional target opportunity, not a forecast or guaranteed sale.
- ASM peers are MIO/SPO positions; RSM peers are rolled-up ASM teams; HOD peers
  are rolled-up RSM teams. Individuals never receive subordinate rankings.
- Vacancy uses blank employee names or explicit VACANT/UNMANNED names.
- National orphan position records are reported as mapping exceptions separately
  from the existing staff-scoped actuals. They are never assigned to an employee.
- Product and customer concentration use positive sales so returns cannot inflate
  concentration through a reduced denominator. Product gaps use gross product
  shortfalls; product overachievement does not reduce that denominator.
- `cyp` is not assumed to mean actual COGS. There is no verified actual COGS column,
  so margin warnings are not fabricated from COGS targets alone.

The data inspected during implementation contains July/August 2026 sales and a
Stock evidence is currently disabled because the available inventory source is
incomplete. Consequently stock-based findings are omitted until a complete
inventory history is available. July/August stock and three-month trend
findings are unavailable until matching data is loaded.

## Validation

Run from the project root:

```text
python -m unittest discover -s tests -v
node tests/test_ai_frontend.cjs
node --check js/ai-insights.js
node --check js/api.js
```

Tests use synthetic fixtures only. Live read-only FastAPI checks cover national,
team, employee, designation, product and product-group filters, invalid inputs,
and the existing home/KPI endpoints. Browser layout still requires a visual check
because no browser surface was connected during implementation.

Restart `python server.py` to load backend changes. Static asset versions were
updated to avoid retaining the previous insight renderer in the browser cache.
