"""Constrained natural-language-to-SQL planner for dashboard sales data.

The model selects an allowlisted query plan. SQL identifiers and expressions are
owned by this module; the model never supplies executable SQL or bind values for
the authenticated position scope.
"""

import datetime as dt
import json
import re
import urllib.error
import urllib.request


class ChatPlanningError(Exception):
    pass


class UnsupportedQuestion(Exception):
    pass


MEASURES = {
    "net_sales": ("Net sales", "COALESCE(SUM(COALESCE(s.net_sale_value,0)),0)", "tgt_net_w_reg", "money"),
    "dashboard_net_sales": ("Dashboard Net Sale Value", "COALESCE(SUM(COALESCE(s.net_wo_reg_disc_value,0)),0)", "tgt_net_wo_reg", "money"),
    "gross_tp": ("TP value", "COALESCE(SUM(COALESCE(s.tp_sale_value,0)),0)", "tgt_tp_value", "money"),
    "units": ("Equivalent units", "COALESCE(SUM(COALESCE(s.e_qty,0)),0)", "tgt_unit", "count"),
    "cyp": ("CYP", "COALESCE(SUM(COALESCE(s.cyp,0)),0)", "tgt_cyps", "money"),
    "discount_rate": ("Discount rate", "100.0 * SUM(COALESCE(s.tp_sale_value,0)-COALESCE(s.net_sale_value,0)) / NULLIF(SUM(COALESCE(s.tp_sale_value,0)),0)", None, "percent"),
    "active_shops": ("Active shops", "COUNT(DISTINCT s.cust_number) FILTER (WHERE COALESCE(s.net_sale_value,0)>0)", None, "count"),
    "returns": ("Return impact", "COALESCE(SUM(ABS(s.net_sale_value)) FILTER (WHERE s.net_sale_value<0 OR s.net_qty<0 OR s.net_value<0),0)", None, "money"),
    "transactions": ("Sales records", "COUNT(*)", None, "count"),
}

TARGET_SUFFIXES = {
    "jul_26", "aug_26", "sep_26", "oct_26", "nov_26", "dec_26",
    "jan_27", "feb_27", "mar_27", "apr_27", "may_27", "jun_27",
}

DIMENSIONS = {
    "total": ("'Total'", "'Total'", "'Total'"),
    "product": ("COALESCE(NULLIF(TRIM(s.product_no::text),''),'Unmapped')", "COALESCE(NULLIF(TRIM(t.product_no::text),''),'Unmapped')", "COALESCE(MAX(NULLIF(TRIM(s.prd_name),'')), COALESCE(NULLIF(TRIM(s.product_no::text),''),'Unmapped')) || ' [' || COALESCE(NULLIF(TRIM(s.product_no::text),''),'Unmapped') || ']'"),
    "employee": ("COALESCE(NULLIF(TRIM(s.position_code::text),''),'Unmapped')", "COALESCE(NULLIF(TRIM(t.position_code_2026_27::text),''),'Unmapped')", "COALESCE(MAX(NULLIF(TRIM(m.employee_name),'')), COALESCE(NULLIF(TRIM(s.position_code::text),''),'Unmapped')) || ' [' || COALESCE(NULLIF(TRIM(s.position_code::text),''),'Unmapped') || ']'"),
    "customer": ("COALESCE(NULLIF(TRIM(s.cust_number::text),''),'Unmapped')", None, "COALESCE(MAX(NULLIF(TRIM(s.cust_name),'')), COALESCE(NULLIF(TRIM(s.cust_number::text),''),'Unmapped')) || ' [' || COALESCE(NULLIF(TRIM(s.cust_number::text),''),'Unmapped') || ']'"),
    "region": ("COALESCE(NULLIF(TRIM(m.region_name),''),'Unmapped')", "COALESCE(NULLIF(TRIM(m.region_name),''),'Unmapped')", "COALESCE(NULLIF(TRIM(m.region_name),''),'Unmapped')"),
    "zone": ("COALESCE(NULLIF(TRIM(m.zone_name),''),'Unmapped')", "COALESCE(NULLIF(TRIM(m.zone_name),''),'Unmapped')", "COALESCE(NULLIF(TRIM(m.zone_name),''),'Unmapped')"),
    "subzone": ("COALESCE(NULLIF(TRIM(m.sub_zone),''),'Unmapped')", "COALESCE(NULLIF(TRIM(m.sub_zone),''),'Unmapped')", "COALESCE(NULLIF(TRIM(m.sub_zone),''),'Unmapped')"),
    "team": ("CASE WHEN UPPER(TRIM(s.team))='PHARMACEUTICAL' THEN 'PHARMA' ELSE 'FMCG' END", "CASE WHEN UPPER(TRIM(t.team))='PHARMACEUTICAL' THEN 'PHARMA' ELSE 'FMCG' END", "CASE WHEN UPPER(TRIM(s.team))='PHARMACEUTICAL' THEN 'PHARMA' ELSE 'FMCG' END"),
    "month": ("s.reporting_month", None, "s.reporting_month"),
}

OPTIONS = {
    "measure": [*MEASURES, "unsupported"],
    "comparison": ["value", "target", "achievement", "gap", "budget"],
    "dimension": list(DIMENSIONS),
    "period": ["dashboard", "previous_month", "last_3_months", "fiscal_ytd"],
    "order": ["highest", "lowest"],
    "search": [""],
}

PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "measure": {"type": "string", "enum": OPTIONS["measure"]},
        "comparison": {"type": "string", "enum": OPTIONS["comparison"]},
        "dimension": {"type": "string", "enum": OPTIONS["dimension"]},
        "period": {"type": "string", "enum": OPTIONS["period"]},
        "order": {"type": "string", "enum": OPTIONS["order"]},
        "search": {"type": "string"},
        "limit": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["measure", "comparison", "dimension", "period", "order", "search", "limit", "reason"],
}

PLANNER_INSTRUCTIONS = """You translate a sales dashboard question into one JSON query plan. Do not write SQL or an answer.
Use only the enums in the schema. The application compiles safe PostgreSQL and computes the answer.
Metric definitions: net_sales=SUM(sales_data.net_sale_value), dashboard_net_sales=SUM(net_wo_reg_disc_value) as shown by the dashboard Net Sale Value card, gross_tp=SUM(tp_sale_value), units=SUM(e_qty) equivalent units, cyp=SUM(cyp), discount_rate=100*(TP-net_sale_value)/TP, active_shops=distinct cust_number with positive net_sale_value, returns=return impact (SUM ABS(net_sale_value) where net_sale_value, net_qty, or net_value is negative), transactions=row count.
For 'against target', choose comparison achievement. For 'shortfall/gap', choose gap; highest gap means largest shortfall. For discount versus budget, choose discount_rate + budget. For a plain amount, choose value. Target comparison is available for net_sales, dashboard_net_sales, gross_tp, units and cyp. Target comparisons cannot be grouped by customer or month. Discount budget compares rate in percentage points.
Choose dimension total for a single overall result, otherwise product, employee (individual position, not manager team rollup), customer, region, zone, subzone, team, or month. For a named entity, choose that dimension and put only the name or code in search. Search filters the grouped label; empty search means no name filter. Use selected dashboard scope and period unless the question explicitly requests previous month, last three months, or fiscal YTD. If a question asks for a different named month or geography, mark unsupported and tell the user to change dashboard filters. A 'trend' needs dimension month and period last_3_months or fiscal_ytd.
For 'why', choose a gap breakdown by product or employee, and make reason say this identifies contributors, not proven causes. If the request cannot be answered by this catalog, choose measure unsupported and give a short reason. Never infer a causal explanation or invent a field. Limit 1 to 10, normally 5. Return JSON only."""


def plan_question(question, filters, api_key, model="gemini-3.6-flash"):
    if not api_key:
        raise ChatPlanningError("Text-to-SQL is not configured. Set GEMINI_API_KEY on the dashboard server.")
    context = json.dumps({
        "question": question,
        "dashboard_context": {key: filters.get(key) for key in ("team", "designation", "region", "zone", "subzone", "territory", "employee", "month", "fy", "period")},
    })
    text = _plan_with_gemini(context, api_key, model)
    try:
        plan = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ChatPlanningError("The planner returned an invalid query plan.") from exc
    return validate_plan(plan)


def _post_plan(request):
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise ChatPlanningError("Gemini's request limit has been reached. Try again shortly.") from exc
        raise ChatPlanningError(f"Gemini returned HTTP {exc.code}. Check GEMINI_API_KEY and GEMINI_MODEL.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ChatPlanningError("Gemini is unavailable. Try again shortly.") from exc
    except (TypeError, ValueError) as exc:
        raise ChatPlanningError("Gemini returned an invalid response.") from exc
    if not isinstance(body, dict):
        raise ChatPlanningError("Gemini returned an invalid response.")
    return body


def _plan_with_gemini(context, api_key, model):
    if not re.fullmatch(r"gemini-[A-Za-z0-9._-]+", model):
        raise ChatPlanningError("GEMINI_MODEL must be a Gemini model ID, such as gemini-3.6-flash.")
    payload = {
        "systemInstruction": {"parts": [{"text": PLANNER_INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": context}]}],
        "generationConfig": {
            "maxOutputTokens": 2000,
            "temperature": 0,
            "responseFormat": {"text": {"mimeType": "APPLICATION_JSON", "schema": PLAN_SCHEMA}},
        },
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    body = _post_plan(request)
    candidates = body.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    if candidate.get("finishReason") not in (None, "STOP"):
        raise ChatPlanningError("Gemini did not return a complete query plan.")
    text = "".join(part.get("text", "") for part in candidate.get("content", {}).get("parts", []))
    if not text:
        raise ChatPlanningError("Gemini did not return a query plan.")
    return text


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != set(PLAN_SCHEMA["required"]):
        raise ChatPlanningError("The planner returned an incomplete query plan.")
    for field in ("measure", "comparison", "dimension", "period", "order"):
        if plan[field] not in OPTIONS[field]:
            raise ChatPlanningError(f"The planner returned an unsupported {field}.")
    if not isinstance(plan["search"], str) or len(plan["search"]) > 120:
        raise ChatPlanningError("The planner returned an invalid name filter.")
    if not isinstance(plan["limit"], int) or isinstance(plan["limit"], bool):
        raise ChatPlanningError("The planner returned an invalid row limit.")
    if not isinstance(plan["reason"], str) or len(plan["reason"]) > 300:
        raise ChatPlanningError("The planner returned an invalid explanation.")
    plan["limit"] = max(1, min(10, plan["limit"]))
    plan["search"] = plan["search"].strip()
    if plan["measure"] == "unsupported":
        raise UnsupportedQuestion(plan["reason"] or "This question needs data outside the supported sales catalog.")
    if plan["search"] and plan["dimension"] == "total":
        raise UnsupportedQuestion("Choose a product, employee, customer, or area grouping for a named result.")
    needs_target = plan["comparison"] != "value"
    if needs_target and plan["dimension"] in {"customer", "month"}:
        raise UnsupportedQuestion("Target comparisons are unavailable by customer or month.")
    if plan["measure"] == "discount_rate":
        if plan["comparison"] not in {"value", "budget"}:
            raise UnsupportedQuestion("Discount rate supports an actual value or a budget comparison.")
    elif plan["comparison"] == "budget":
        raise UnsupportedQuestion("Budget comparison is available only for discount rate.")
    elif needs_target and MEASURES[plan["measure"]][2] is None:
        raise UnsupportedQuestion("A verified target is unavailable for that measure.")
    return plan


def _fiscal_year(date):
    start = date.year if date.month >= 7 else date.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def selected_months(plan, filters):
    selected = dt.datetime.strptime(filters["month"], "%b-%Y")
    prior = (selected.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    period = plan["period"]
    if period == "previous_month":
        dates = [prior]
    elif period == "last_3_months":
        second_prior = (prior - dt.timedelta(days=1)).replace(day=1)
        dates = [second_prior, prior, selected]
    elif period == "fiscal_ytd" or (period == "dashboard" and filters["period"] == "YTD"):
        first = dt.datetime(selected.year if selected.month >= 7 else selected.year - 1, 7, 1)
        dates = []
        current = first
        while current <= selected:
            dates.append(current)
            current = (current.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    else:
        dates = [selected]
    return dates


def compile_query(plan, filters, positions, team_predicate):
    dates = selected_months(plan, filters)
    month_labels = [date.strftime("%B,%y") for date in dates]
    fiscal_years = sorted({_fiscal_year(date) for date in dates})
    measure_label, actual_expr, target_prefix, _ = MEASURES[plan["measure"]]
    actual_key, target_key, actual_label = DIMENSIONS[plan["dimension"]]
    needs_target = plan["comparison"] != "value"
    if needs_target and any(_fiscal_year(date) != "2026-27" or date.strftime("%b_%y").lower() not in TARGET_SUFFIXES for date in dates):
        raise UnsupportedQuestion("Targets are available only for FY 2026-27. Select a supported period.")
    if needs_target and filters["fy"] != "2026-27" and plan["period"] == "dashboard":
        raise UnsupportedQuestion("Targets are unavailable for the selected fiscal year.")

    actual_group = "" if plan["dimension"] == "total" else f"GROUP BY {actual_key}"
    target_group = "" if plan["dimension"] == "total" else f"GROUP BY {target_key}"
    staff_dimension = plan["dimension"] in {"employee", "region", "zone", "subzone"}
    actual_staff_join = "LEFT JOIN public.staff_master m ON m.position_code = s.position_code" if staff_dimension else ""
    target_staff_join = "LEFT JOIN public.staff_master m ON m.position_code = t.position_code_2026_27" if staff_dimension else ""
    sql = f"""WITH scope(position_code) AS (
        SELECT DISTINCT position_code FROM unnest(%s::text[]) AS allowed(position_code)
    ), sales_base AS (
        SELECT s.*
        FROM public.sales_data s
        JOIN scope allowed ON allowed.position_code = s.position_code
        WHERE s.reporting_month = ANY(%s::text[])
          AND s.fiscal_year = ANY(%s::text[])
          AND {team_predicate('s.team', filters['team'])}
    ), actual AS (
        SELECT {actual_key} AS key, {actual_label} AS label,
               {actual_expr} AS actual
        FROM sales_base s
        {actual_staff_join}
        {actual_group}
    )"""
    params = [list(positions), month_labels, fiscal_years]
    if needs_target:
        suffixes = [date.strftime("%b_%y").lower() for date in dates]
        if plan["measure"] == "discount_rate":
            numerator = " + ".join(f"COALESCE(t.tgt_add_disc_value_{suffix},0)+COALESCE(t.tgt_reg_disc_value_{suffix},0)" for suffix in suffixes)
            denominator = " + ".join(f"COALESCE(t.tgt_tp_value_{suffix},0)" for suffix in suffixes)
            target_expr = f"100.0 * SUM({numerator}) / NULLIF(SUM({denominator}),0)"
        else:
            target_expr = "SUM(" + " + ".join(f"COALESCE(t.{target_prefix}_{suffix},0)" for suffix in suffixes) + ")"
        sql += f""", targets AS (
        SELECT {target_key} AS key, {target_expr} AS target
        FROM public.target_data t
        JOIN scope allowed ON allowed.position_code = t.position_code_2026_27
        {target_staff_join}
        WHERE {team_predicate('t.team', filters['team'])}
        {target_group}
    )
    SELECT COALESCE(a.label, t.key) AS label, COALESCE(a.actual,0) AS actual,
           t.target AS target,
           100.0 * COALESCE(a.actual,0) / NULLIF(t.target,0) AS achievement_pct,
           t.target - COALESCE(a.actual,0) AS gap,
           (SELECT COUNT(*) FROM sales_base) AS source_rows
    FROM actual a FULL JOIN targets t ON t.key = a.key"""
        sort_field = {"value": "actual", "target": "target", "achievement": "achievement_pct",
                      "gap": "gap", "budget": "gap"}[plan["comparison"]]
    else:
        sql += """
    SELECT a.label, a.actual, NULL::numeric AS target,
           NULL::numeric AS achievement_pct, NULL::numeric AS gap,
           (SELECT COUNT(*) FROM sales_base) AS source_rows
    FROM actual a"""
        sort_field = "actual"
    if plan["search"]:
        sql += " WHERE COALESCE(a.label, t.key) ILIKE %s" if needs_target else " WHERE a.label ILIKE %s"
        params.append("%" + plan["search"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        sql += " ESCAPE '\\'"
    direction = "DESC" if plan["order"] == "highest" else "ASC"
    if plan["dimension"] == "month":
        sql += " ORDER BY to_date(a.key, 'FMMonth,YY') ASC"
    else:
        sql += f" ORDER BY {sort_field} {direction} NULLS LAST, label ASC"
    sql += " LIMIT %s"
    params.append(1 if plan["dimension"] == "total" else len(month_labels) if plan["dimension"] == "month" else plan["limit"])
    return sql, params, month_labels, measure_label


def format_answer(plan, filters, rows, months):
    measure_label, _, _, unit = MEASURES[plan["measure"]]
    period_label = ", ".join(months)
    scope_parts = [filters.get("team"), filters.get("designation"), filters.get("employee"),
                   filters.get("region"), filters.get("zone"), filters.get("subzone"), filters.get("territory")]
    scope = " · ".join(str(part) for part in scope_parts if part and str(part).lower() != "all")
    scope = f"{scope} · {period_label}" if scope else period_label
    if not rows:
        return "No matching records were found for this question and selected scope.", scope
    if plan["comparison"] != "target" and not rows[0][5]:
        return "No sales records are loaded for this period and scope. I cannot infer performance from a zero result.", scope
    if plan["comparison"] != "value" and all(row[2] is None for row in rows):
        return "No comparable targets are loaded for this period and scope.", scope

    def number(value):
        if value is None:
            return "N/A"
        if unit == "percent":
            return f"{float(value):,.1f}%"
        if unit == "count":
            return f"{float(value):,.0f}"
        return f"PKR {float(value):,.0f}"

    parts = []
    for label, actual, target, achievement, gap, _ in rows:
        name = str(label or "Unmapped")
        comparison = plan["comparison"]
        if comparison == "value":
            detail = number(actual)
        elif comparison == "target":
            detail = f"target {number(target)}"
        elif comparison == "budget":
            variance = None if target is None or actual is None else float(actual) - float(target)
            detail = f"actual {number(actual)}, budget {number(target)}"
            if variance is not None:
                detail += f", {abs(variance):.1f} percentage points {'above' if variance > 0 else 'below' if variance < 0 else 'on'} budget"
        else:
            detail = f"actual {number(actual)}, target {number(target)}"
            if comparison == "achievement":
                detail += f", achievement {float(achievement):.1f}%" if achievement is not None else ", achievement N/A"
            else:
                detail += f", {'shortfall' if gap is not None and float(gap) >= 0 else 'surplus'} {number(abs(float(gap)) if gap is not None else None)}"
        parts.append(f"{name}: {detail}")
    heading = f"{measure_label} for {scope}."
    if plan["dimension"] == "total":
        answer = f"{heading} {parts[0]}"
    else:
        answer = f"{heading} {'; '.join(parts)}."
    if "contributor" in plan["reason"].lower() or "not proven" in plan["reason"].lower():
        answer += " These are contributors to the gap, not proven causes."
    return answer, scope
