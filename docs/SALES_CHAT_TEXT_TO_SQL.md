# Sales Analyst text-to-SQL chatbot

The Sales Analyst sits below AI Sales Insights. `POST /api/sales-chat` sends the
question and current dashboard filters to Gemini. The model selects a
structured query plan. The server builds read-only PostgreSQL from allowlisted
tables, columns, measures, dimensions, and time periods, binds user text as a
parameter, and restricts sales and targets to the signed-in user's authorized
position codes. The model never supplies SQL to execute and receives no database
rows. The response is calculated from query results and includes the SQL for
inspection in the chatbot.

## Setup

Add the following lines to the project root `.env` file (the one beside
`scripts`, shown in VS Code), replacing the key placeholder:

```text
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=gemini-3.6-flash
```

The key may also be supplied as a server environment variable. Keep it on
the server; the browser never needs it. Restart `python scripts/server.py`,
sign in, and ask a question in the Sales Analyst panel. Without a Gemini key,
the endpoint returns a setup error instead of an invented answer. The default
model is `gemini-3.6-flash` and can be changed with `GEMINI_MODEL`.

## Supported questions

- Net sales, dashboard Net Sale Value, TP value, equivalent units, CYP,
  discount rate, active shops, returns, and sales record count.
- Totals or breakdowns by product, individual position, customer, region,
  zone, subzone, team, or reporting month.
- Rankings, named product/employee/customer/area filters, previous month,
  last three months, and fiscal year to date.
- FY 2026-27 target, achievement, and gap for measures with mapped targets.
  Discount rate can be compared with its budget rate.

Target comparisons by customer or reporting month are unavailable. Named months
outside the selected dashboard month require changing dashboard filters. The
chatbot states when a question cannot be answered from this catalog or a period
has no loaded sales data. A gap breakdown identifies contributors, not causes.

The model chooses the metric and grouping, so review the displayed SQL and
selected filters when a business term is ambiguous. The server calculates the
figures; it does not ask the model to invent an answer.
