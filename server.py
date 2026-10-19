"""
Executive Dashboard API
-----------------------
Serves the static dashboard and the JSON endpoints it needs.

Tables used (all joined through POSITION_CODE):
  * staff_master : hierarchy (report_to_position_code), designation, region/zone
  * sales_data   : actuals
  * target_data  : monthly targets (position_code_2026_27)
  * Inventory/stock ledger is intentionally not queried by this application.

Run:  python server.py     ->  http://localhost:8000
"""
import datetime as dt
import contextvars
import hashlib
import threading
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from psycopg2.pool import ThreadedConnectionPool
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from performance_monitor import (
    DatabasePoolTimeout, EndpointTimingMiddleware, PoolMetrics,
    query_identifier, run_query,
)
from response_cache import TTLResponseCache

import sys

ROOT = Path(__file__).parent
EXECUTIVE_DIR = ROOT / "executive_website"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ----------------------------------------------------------------- config
def load_env(path: Path) -> dict:
    """Tiny .env parser that tolerates inline '# comments'."""
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = load_env(ROOT / ".env")


def bounded_int_setting(name, default, minimum, maximum):
    try:
        value = int(ENV.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


DB_POOL_MIN = bounded_int_setting("DB_POOL_MIN", 1, 1, 20)
DB_POOL_MAX = bounded_int_setting("DB_POOL_MAX", 5, DB_POOL_MIN, 30)
DB_POOL_ACQUIRE_TIMEOUT_SECONDS = bounded_int_setting(
    "DB_POOL_ACQUIRE_TIMEOUT_SECONDS", 5, 1, 60,
)
DB_CONNECT_TIMEOUT_SECONDS = bounded_int_setting("DB_CONNECT_TIMEOUT_SECONDS", 5, 1, 60)
DB_STATEMENT_TIMEOUT_MS = bounded_int_setting("DB_STATEMENT_TIMEOUT_MS", 15000, 1000, 300000)
DB_IDLE_TRANSACTION_TIMEOUT_MS = bounded_int_setting(
    "DB_IDLE_TRANSACTION_TIMEOUT_MS", 30000, 1000, 300000,
)
DB_KEEPALIVES_IDLE_SECONDS = bounded_int_setting("DB_KEEPALIVES_IDLE_SECONDS", 30, 10, 300)
DB_KEEPALIVES_INTERVAL_SECONDS = bounded_int_setting("DB_KEEPALIVES_INTERVAL_SECONDS", 10, 5, 120)
DB_KEEPALIVES_COUNT = bounded_int_setting("DB_KEEPALIVES_COUNT", 5, 1, 10)
pool = ThreadedConnectionPool(
    DB_POOL_MIN, DB_POOL_MAX,
    host=ENV["DB_HOST"], port=int(ENV["DB_PORT"]), dbname=ENV["DB_NAME"],
    user=ENV["DB_USER"], password=ENV["DB_PASSWORD"],
    connect_timeout=DB_CONNECT_TIMEOUT_SECONDS,
    application_name="executive-dashboard",
    keepalives=1,
    keepalives_idle=DB_KEEPALIVES_IDLE_SECONDS,
    keepalives_interval=DB_KEEPALIVES_INTERVAL_SECONDS,
    keepalives_count=DB_KEEPALIVES_COUNT,
    options=(
        f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} "
        f"-c idle_in_transaction_session_timeout={DB_IDLE_TRANSACTION_TIMEOUT_MS}"
    ),
)
query_slots = threading.BoundedSemaphore(DB_POOL_MAX)
pool_metrics = PoolMetrics(DB_POOL_MAX)
SALES_SUMMARIES_ENABLED = ENV.get("SALES_SUMMARIES_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on",
}


CACHE_ENABLED = ENV.get("DASHBOARD_CACHE_ENABLED", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
CACHE_TTL_SECONDS = bounded_int_setting("DASHBOARD_CACHE_TTL_SECONDS", 600, 300, 900)
CACHE_MAX_ENTRIES = bounded_int_setting("DASHBOARD_CACHE_MAX_ENTRIES", 128, 16, 1024)
response_cache = TTLResponseCache(CACHE_TTL_SECONDS, CACHE_MAX_ENTRIES, CACHE_ENABLED)
scope_cache = TTLResponseCache(CACHE_TTL_SECONDS, min(CACHE_MAX_ENTRIES * 2, 2048), CACHE_ENABLED)
metadata_cache = TTLResponseCache(CACHE_TTL_SECONDS, 16, CACHE_ENABLED)

# Kept as a fallback for startup and the dashboard's generic layout. The API
# replaces this with the complete distinct list from staff_master.
DESIGNATIONS = ["ALL", "SPO", "MIO", "ASM", "RSM", "HOD"]
TARGET_FY = "2026-27"  # target_data only holds FY 2026-27
FILTER_HIDDEN_DESIGNATIONS = {"EXEC", "HOD", "DGM"}

# Numeric sales columns are stored as NUMERIC in PostgreSQL.
# Keep NULL values safe for dashboard aggregates.
def num(col: str) -> str:
    return f"COALESCE({col}, 0)"


def query(sql: str, params: list, query_id: str = None):
    query_id = query_id or query_identifier(sql)
    rows, _ = run_query(
        pool, sql, params, query_id, query_slots,
        DB_POOL_ACQUIRE_TIMEOUT_SECONDS, pool_metrics,
    )
    return rows


def submit_query(executor, query_id, sql, params):
    """Keep the endpoint label when KPI queries run in a worker thread."""
    context = contextvars.copy_context()
    return executor.submit(context.run, query, sql, params, query_id)


def dashboard_data_generation():
    """Read the transactionally updated cache generation; failure disables caching."""
    if not CACHE_ENABLED:
        return None
    try:
        rows = query(
            "SELECT generation FROM public.dashboard_cache_generation WHERE singleton = true",
            [], "cache.generation",
        )
        return int(rows[0][0]) if rows else None
    except Exception:
        return None


def authorized_scope_digest(position_codes):
    """Opaque identity for the exact authorized position set; logs never include it."""
    digest = hashlib.blake2s(digest_size=16)
    for code in sorted(str(code) for code in position_codes if code is not None):
        digest.update(code.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def cached_authorized_positions(generation, designation, region, zone, subzone,
                                territory, employee, team):
    compute = lambda: resolve_authorized_positions(
        designation, region, zone, subzone, territory, employee, team,
    )
    if generation is None:
        return compute()
    scope_cache.sync_generation(generation)
    key = (generation, "scope", designation, region, zone, subzone, territory, employee, team)
    return scope_cache.get_or_compute(key, compute)


def cached_response(generation, key, compute):
    """Fail open to the normal database path when invalidation is unavailable."""
    if generation is None:
        return compute()
    response_cache.sync_generation(generation)
    return response_cache.get_or_compute((generation, *key), compute)


def cached_summary_readiness(generation):
    if generation is None:
        return sales_summaries_ready()
    metadata_cache.sync_generation(generation)
    return metadata_cache.get_or_compute(
        (generation, "sales_summaries_ready"), sales_summaries_ready,
    )


SUMMARY_METRICS = {
    "tp_sale_value": "gross_tp_value",
    "net_sale_value": "net_sale_value",
    "e_qty": "units",
    "net_wo_reg_disc_value": "net_wo_reg_disc_value",
    "cyp": "cyp",
}


def sales_summaries_ready(periods=None):
    """Return True only for a complete, clean summary snapshot.

    A missing migration, incomplete backfill, or pending source correction keeps
    the request on the existing raw-query path. ``periods=None`` additionally
    requires every source period to have a refresh-state row; this is used by
    calculations such as first-ever customer activity.
    """
    if not SALES_SUMMARIES_ENABLED:
        return False
    tables = query(
        """SELECT to_regclass('public.sales_monthly_position_summary'),
                  to_regclass('public.sales_monthly_product_summary'),
                  to_regclass('public.sales_monthly_customer_summary'),
                  to_regclass('public.sales_monthly_position_product_summary'),
                  to_regclass('public.sales_monthly_summary_refresh_state'),
                  to_regclass('public.sales_monthly_summary_dirty_period')""",
        [], "summaries.catalog",
    )[0]
    if any(table is None for table in tables):
        return False
    if periods is None:
        ready = query(
            """SELECT NOT EXISTS (
                     SELECT 1 FROM public.sales_monthly_summary_dirty_period)
                   AND EXISTS (
                     SELECT 1 FROM public.sales_monthly_summary_refresh_state)""",
            [], "summaries.freshness_all",
        )
    else:
        unique_periods = list(dict.fromkeys(periods))
        months = [period[0] for period in unique_periods]
        years = [period[1] for period in unique_periods]
        ready = query(
            """WITH required(reporting_month, fiscal_year) AS (
                 SELECT * FROM unnest(%s::text[], %s::text[]))
               SELECT NOT EXISTS (
                 SELECT 1 FROM required r
                 LEFT JOIN public.sales_monthly_summary_refresh_state s
                   USING (reporting_month, fiscal_year)
                 LEFT JOIN public.sales_monthly_summary_dirty_period d
                   USING (reporting_month, fiscal_year)
                 WHERE s.reporting_month IS NULL OR d.reporting_month IS NOT NULL)""",
            [months, years], "summaries.freshness_periods",
        )
    return bool(ready and ready[0][0])


# ------------------------------------------------------------ hierarchy
INDIVIDUAL = {"MIO", "SPO", "PS", "SB", "ASMTE", "CM", "SPOWS", "TE"}  # field force: own sales & targets only


def team_predicate(column: str, team: str) -> str:
    """Match only the two supported business teams, using a TEAM column."""
    normalized = f"UPPER(TRIM(COALESCE({column}, '')))"
    fmcg = f"{normalized} LIKE 'FAST MOVING CONSUMER GOODS%%'"
    pharma = f"{normalized} = 'PHARMACEUTICAL'"
    if team == "FMCG":
        return fmcg
    if team == "PHARMA":
        return pharma
    return f"({fmcg} OR {pharma})"


def scope_mode(designation: str) -> str:
    return "individual" if designation in INDIVIDUAL else "rollup"


def hierarchy_scope_cte(designation: str, region: str, zone: str, subzone: str,
                        territory: str = "All", employee: str = "All",
                        team: str = "COMBINED"):
    """Build the authoritative staff hierarchy CTE and its parameters."""
    where, params = [team_predicate("staff_master.team_name", team)], []
    all_designations = designation in {"ALL", "All"}
    has_terr = bool(territory) and territory != "All"
    national = designation == "HOD" and not has_terr and employee == "All"
    if not national and not all_designations:
        where.append("designation_name = %s")
        params.append(designation)
    for col, val in (("region_name", region), ("zone_name", zone), ("sub_zone", subzone),
                     ("dept_territory_code", territory), ("employee_name", employee)):
        if val and val != "All":
            # Dropdown values and incoming parameters are normalized.  This
            # keeps a territory code from resolving no positions merely
            # because the source import contains trailing whitespace.
            where.append(f"TRIM({col}) = %s")
            params.append(str(val).strip())
    predicates = " AND ".join(where) or "TRUE"
    if national or all_designations or designation in INDIVIDUAL:
        sql = f"WITH scope AS (SELECT position_code FROM staff_master WHERE {predicates})"
    else:
        sql = (
            "WITH RECURSIVE scope AS ("
            f"SELECT position_code FROM staff_master WHERE {predicates} "
            "UNION SELECT m.position_code FROM staff_master m "
            "JOIN scope s ON m.report_to_position_code = s.position_code "
            f"WHERE {team_predicate('m.team_name', team)})"
        )
    return sql, params


def resolve_authorized_positions(designation: str, region: str, zone: str, subzone: str,
                                 territory: str = "All", employee: str = "All",
                                 team: str = "COMBINED"):
    """Resolve and deduplicate a dashboard's authorized positions once per request."""
    hierarchy_cte, params = hierarchy_scope_cte(
        designation, region, zone, subzone, territory, employee, team,
    )
    rows = query(
        f"{hierarchy_cte} SELECT DISTINCT position_code FROM scope "
        "WHERE position_code IS NOT NULL ORDER BY position_code",
        params,
        "hierarchy.authorized_scope",
    )
    # Keep this defensive deduplication for test doubles and malformed staff imports.
    return list(dict.fromkeys(row[0] for row in rows if row and row[0] is not None))


def resolve_reporting_tree(position_code: str):
    """Resolve a manager and all descendants for the AI parent comparison."""
    rows = query(
        """WITH RECURSIVE scope AS (
          SELECT position_code FROM staff_master WHERE position_code = %s
          UNION
          SELECT m.position_code FROM staff_master m
          JOIN scope parent ON m.report_to_position_code = parent.position_code
        )
        SELECT DISTINCT position_code FROM scope
        WHERE position_code IS NOT NULL ORDER BY position_code""",
        [position_code],
        "hierarchy.reporting_tree",
    )
    return list(dict.fromkeys(row[0] for row in rows if row and row[0] is not None))


def scope_cte(designation: str, region: str, zone: str, subzone: str, territory: str = "All",
              employee: str = "All", team: str = "COMBINED", target_suffix: str = None,
              resolved_positions=None):
    """
    Build a CTE `scope(position_code)`:
      * MIO / SPO -> only the selected position(s): individual sales & targets
      * HOD (no territory chosen) -> every position (national view)
      * ASM / RSM / HOD(+territory) -> the position(s) + everyone reporting under them
                 (recursive over report_to_position_code) = roll-up of lower levels

    A request can pass its pre-resolved scope so related queries do not repeat
    the recursive staff traversal on separate pooled connections.
    Region / Zone / Sub Zone / Dept. Territory Code narrow the starting positions.
    """
    if resolved_positions is None:
        sql, params = hierarchy_scope_cte(
            designation, region, zone, subzone, territory, employee, team,
        )
    else:
        positions = list(dict.fromkeys(
            position for position in resolved_positions if position is not None
        ))
        sql = (
            "WITH scope(position_code) AS ("
            "SELECT DISTINCT position_code FROM unnest(%s::text[]) AS resolved(position_code))"
        )
        params = [positions]
    # Keep only columns read by the KPI and AI queries. The source tables are
    # wide, especially target_data with one set of columns per target month.
    sales_columns = (
        "team", "position_code", "reporting_month", "fiscal_year", "tp_sale_value",
        "net_sale_value", "e_qty", "net_wo_reg_disc_value", "cyp", "cust_number",
        "bonus_discount", "group_on", "prd_name", "mnp_commission", "cust_name",
        "product_no", "net_qty", "discounts", "net_value", "depot_name",
    )
    target_months = (
        "jul_26", "aug_26", "sep_26", "oct_26", "nov_26", "dec_26",
        "jan_27", "feb_27", "mar_27", "apr_27", "may_27", "jun_27",
    )
    target_prefixes = (
        "tgt_tp_value", "tgt_net_w_reg", "tgt_unit", "tgt_net_wo_reg",
        "tgt_cyps", "tgt_add_disc_value", "tgt_reg_disc_value",
    )
    months = (target_suffix,) if target_suffix in target_months else target_months
    target_columns = ("team", "position_code_2026_27", "product_group_on_master", "product_no") + tuple(
        f"{prefix}_{suffix}" for suffix in months for prefix in target_prefixes
    )
    sql += (
        ", sales_data AS (SELECT " + ", ".join(f"s.{col}" for col in sales_columns)
        + f" FROM public.sales_data s WHERE {team_predicate('s.team', team)}"
        + ")"
        + ", target_data AS (SELECT " + ", ".join(f"t.{col}" for col in target_columns)
        + f" FROM public.target_data t WHERE {team_predicate('t.team', team)}"
        + ")"
    )
    return sql, params


def designation_options(team: str = "COMBINED"):
    team = (team or "COMBINED").upper()
    conditions = ["NULLIF(TRIM(designation_name), '') IS NOT NULL",
                  "UPPER(TRIM(designation_name)) NOT IN ('EXEC', 'HOD', 'DGM')",
                  team_predicate("team_name", team)]
    params = []
    rows = query(
        "SELECT DISTINCT TRIM(designation_name) FROM staff_master WHERE "
        + " AND ".join(conditions) + " ORDER BY 1",
        params,
    )
    return ["ALL"] + [row[0] for row in rows]


def check_designation(d: str):
    if d in {"ALL", "All"}:
        return
    if not query("SELECT 1 FROM staff_master WHERE designation_name = %s LIMIT 1", [d]):
        raise HTTPException(400, f"Unknown designation '{d}'")


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(_app):
    yield
    pool.closeall()


app = FastAPI(title="Executive Dashboard API", lifespan=lifespan)
app.add_middleware(EndpointTimingMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


@app.exception_handler(DatabasePoolTimeout)
async def database_pool_timeout_handler(_request, _exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Database capacity is temporarily busy; retry shortly."},
        headers={"Retry-After": "1"},
    )


@app.get("/api/meta")
def meta(team: str = "COMBINED"):
    """Months / fiscal years that actually have sales data."""
    team = (team or "COMBINED").upper()
    if team not in {"COMBINED", "FMCG", "PHARMA"}:
        raise HTTPException(400, "team must be COMBINED, FMCG, or PHARMA")
    source = ("public.sales_monthly_position_summary"
              if sales_summaries_ready() else "public.sales_data")
    rows = query(
        f"SELECT DISTINCT reporting_month, fiscal_year FROM {source} "
        f"WHERE {team_predicate('team', team)}", [],
        "meta.summary_periods" if "summary" in source else "meta.raw_periods",
    )
    months, years = {}, set()
    for rm, fy in rows:
        try:
            d = dt.datetime.strptime(rm.strip(), "%B,%y")
        except (ValueError, AttributeError):
            continue
        months[d] = d.strftime("%b-%Y")
        if fy:
            years.add(fy)
    return {
        "designations": designation_options(team),
        "months": [months[k] for k in sorted(months)],
        "fiscal_years": sorted(years, reverse=True),
    }


@app.get("/api/filters")
def filters(designation: str = "ALL", region: str = "All", zone: str = "All",
            subzone: str = "All", territory: str = "All", employee: str = "All",
            team: str = "COMBINED", search_field: str = "", search: str = ""):
    """Return distinct indexed filter choices, not the full staff-master table."""
    check_designation(designation)
    team = (team or "COMBINED").upper()
    if team not in {"COMBINED", "FMCG", "PHARMA"}:
        raise HTTPException(400, "team must be COMBINED, FMCG, or PHARMA")

    columns = {
        "employee": "employee_name", "region": "region_name", "zone": "zone_name",
        "subzone": "sub_zone", "territory": "dept_territory_code",
    }
    selected = {"employee": employee, "region": region, "zone": zone,
                "subzone": subzone, "territory": territory}
    # Geography dropdowns cascade from parent to child. Applying every active
    # value to every option query makes a newly selected parent disappear when
    # an old child value belongs to a different branch. Employee remains the
    # leaf and is narrowed by the complete current scope.
    option_dependencies = {
        "region": (),
        "zone": ("region",),
        "subzone": ("region", "zone"),
        "territory": ("region", "zone", "subzone"),
        "employee": ("region", "zone", "subzone", "territory"),
    }
    base_where, base_params = [], []
    if designation not in {"ALL", "All"}:
        base_where.append("designation_name = %s")
        base_params.append(designation)
    base_where.append(team_predicate("team_name", team))

    options = {}
    partial_search = search_field in columns
    fields_to_query = [(search_field, columns[search_field])] if partial_search else columns.items()
    for field, column in fields_to_query:
        normalized_column = f"NULLIF(TRIM({column}), '')"
        where = [*base_where, f"{normalized_column} IS NOT NULL"]
        params = list(base_params)
        for other_field in option_dependencies[field]:
            value = selected[other_field]
            if value and value != "All":
                where.append(f"TRIM({columns[other_field]}) = %s")
                params.append(str(value).strip())
        if search and search_field == field:
            where.append(f"LOWER(TRIM({column})) LIKE %s")
            params.append(search.strip().lower() + "%")
        limit = 100 if field == "employee" else 1000
        values = [row[0] for row in query(
            f"SELECT DISTINCT {normalized_column} FROM staff_master WHERE "
            + " AND ".join(where) + f" ORDER BY {normalized_column} LIMIT {limit}",
            params,
        )]
        selected_value = selected[field]
        if selected_value and selected_value != "All" and selected_value not in values:
            selected_where = [*where, f"TRIM({column}) = %s"]
            selected_params = [*params, str(selected_value).strip()]
            exists = query(
                f"SELECT {normalized_column} FROM staff_master WHERE " + " AND ".join(selected_where) + " LIMIT 1",
                selected_params,
            )
            if exists:
                values.append(selected_value)
                values.sort()
        options[field] = values

    if partial_search:
        return options
    return {"designation": designation, "designations": designation_options(team), **options}


@app.get("/api/employee-scope")
def employee_scope(employee: str = Query(..., min_length=1)):
    """Return the staff-master scope rows for an exact employee name."""
    employee = employee.strip()
    rows = query(f"""SELECT DISTINCT position_code, employee_name, designation_name,
          team_name, dept_territory_code, region_name, zone_name, sub_zone,
          department_name,
          CASE
            WHEN UPPER(TRIM(team_name)) LIKE '%%PHARM%%' THEN 'PHARMA'
            WHEN UPPER(TRIM(team_name)) LIKE '%%FMCG%%'
              OR UPPER(TRIM(team_name)) LIKE '%%FAST MOVING%%' THEN 'FMCG'
            ELSE 'COMBINED'
          END AS team_filter
        FROM staff_master
        WHERE LOWER(TRIM(employee_name)) = LOWER(%s)
          AND {team_predicate('team_name', 'COMBINED')}
        ORDER BY position_code""", [employee])
    if not rows:
        raise HTTPException(404, f"No staff-master record found for employee '{employee}'")
    records = []
    for row in rows:
        pos_code = row[0] or ""
        dept = pos_code.split('-')[1] if '-' in pos_code and len(pos_code.split('-')) >= 2 else (
            "PHR" if row[9] == "PHARMA" else "FMCG" if row[9] == "FMCG" else (row[8] or "")
        )
        records.append({
            "position_code": row[0], "employee": row[1], "designation": row[2],
            "team": row[3], "territory": row[4], "region": row[5],
            "zone": row[6], "subzone": row[7], "department": dept, "team_filter": row[9]
        })
    return {"records": records}


@app.get("/api/territory-scope")
def territory_scope(territory: str = Query(..., min_length=1)):
    """Return the actual staff-master rows associated with one territory.

    The dashboard uses this only when the Dept Terr Code filter is changed.
    Returning every matching row lets the client select unambiguous values and
    retain a constrained choice list when a territory has more than one owner
    or hierarchy assignment.
    """
    territory = territory.strip()
    rows = query(f"""SELECT DISTINCT position_code,
          NULLIF(TRIM(employee_name), ''), NULLIF(TRIM(designation_name), ''),
          NULLIF(TRIM(team_name), ''), NULLIF(TRIM(dept_territory_code), ''),
          NULLIF(TRIM(region_name), ''), NULLIF(TRIM(zone_name), ''),
          NULLIF(TRIM(sub_zone), ''),
          CASE
            WHEN UPPER(TRIM(team_name)) LIKE '%%FAST MOVING CONSUMER GOODS%%' THEN 'FMCG'
            WHEN UPPER(TRIM(team_name)) = 'PHARMACEUTICAL' THEN 'PHARMA'
            ELSE 'COMBINED'
          END AS team_filter
        FROM staff_master
        WHERE TRIM(dept_territory_code) = %s
          AND {team_predicate('team_name', 'COMBINED')}
        ORDER BY position_code""", [territory], "filters.territory_scope")
    if not rows:
        raise HTTPException(404, f"No staff-master record found for Dept Terr Code '{territory}'")
    return {"records": [
        {
            "position_code": row[0], "employee": row[1], "designation": row[2],
            "team": row[3], "territory": row[4], "region": row[5],
            "zone": row[6], "subzone": row[7], "team_filter": row[8]
        }
        for row in rows
    ]}


def _kpis_uncached(
    designation: str = "HOD", region: str = "All", zone: str = "All", subzone: str = "All",
    territory: str = "All", employee: str = "All", team: str = "COMBINED",
    month: str = Query(..., description="e.g. Jul-2026"), fy: str = TARGET_FY,
    value_metric: str = "net_with_reg", use_summaries=None, resolved_positions=None,
):
    check_designation(designation)
    value_columns = {
        "tp": ("tp_sale_value", "tgt_tp_value", 0, 0, "TP VALUE"),
        # The request parameter is retained for existing dashboard links.
        "net_with_reg": ("net_wo_reg_disc_value", "tgt_net_wo_reg", 3, 3, "NET SALE VALUE"),
        "units": ("e_qty", "tgt_unit", 2, 2, "UNITS"),
        "cyp": ("cyp", "tgt_cyps", 4, 4, "CYP"),
    }
    if value_metric not in value_columns:
        raise HTTPException(400, "invalid value_metric")
    sales_column, target_prefix, sales_index, target_index, metric_label = value_columns[value_metric]
    team = team.upper()
    if team not in {"COMBINED", "FMCG", "PHARMA"}:
        raise HTTPException(400, "team must be COMBINED, FMCG, or PHARMA")
    try:
        d = dt.datetime.strptime(month, "%b-%Y")
    except ValueError:
        raise HTTPException(400, "month must look like Jul-2026")

    sales_month = f"{d.strftime('%B')},{d.strftime('%y')}"          # July,26
    sfx = f"{d.strftime('%b').lower()}_{d.strftime('%y')}"           # jul_26
    # call_data currently contains FMCG records and uses both `Jul-26` and
    # `Jul,26` month styles. Support both while new extracts are standardized.
    call_months = [f"{d.strftime('%b')}-{d.strftime('%y')}", f"{d.strftime('%b')},{d.strftime('%y')}"]
    scope_positions = (resolve_authorized_positions(
        designation, region, zone, subzone, territory, employee, team,
    ) if resolved_positions is None else list(resolved_positions))
    cte, cte_params = scope_cte(
        designation, region, zone, subzone, territory, employee, team, sfx,
        resolved_positions=scope_positions,
    )

    # ---- actuals (sales_data) -------------------------------------------
    sales_sql = f"""{cte}
      SELECT SUM({num('tp_sale_value')}), SUM({num('net_sale_value')}), SUM({num('e_qty')}),
             SUM({num('net_wo_reg_disc_value')}), SUM({num('cyp')}),
             COUNT(DISTINCT cust_number) FILTER (WHERE {num('net_sale_value')} > 0),
             COUNT(DISTINCT position_code) FILTER (WHERE {num('net_sale_value')} > 0),
             SUM(ABS({num('net_sale_value')})) FILTER (WHERE {num('net_sale_value')} < 0),
             SUM({num('net_sale_value')}) FILTER (WHERE {num('net_sale_value')} > 0),
             SUM({num('tp_sale_value')}) FILTER (WHERE {num('tp_sale_value')} > 0),
             SUM({num('bonus_discount')}),
             COUNT(DISTINCT cust_number) FILTER (WHERE cust_number IS NOT NULL)
      FROM sales_data
      WHERE position_code IN (SELECT position_code FROM scope)
        AND reporting_month = %s AND fiscal_year = %s"""
    # Prior month actuals are used by the individual field-force KPI subtitles.
    prev_d = d.replace(day=1) - dt.timedelta(days=1)
    prev_month = f"{prev_d.strftime('%B')},{prev_d.strftime('%y')}"
    if use_summaries is None:
        use_summaries = sales_summaries_ready()
    if use_summaries and scope_mode(designation) == "individual":
        # Single-position plans are already selective on the indexed raw table;
        # live benchmarks showed the summary joins add overhead for this scope.
        use_summaries = False
    summary_team = team_predicate("s.team", team)
    summary_metric = SUMMARY_METRICS[sales_column]
    if use_summaries:
        sales_sql = f"""{cte}, actual AS (
          SELECT SUM(COALESCE(s.gross_tp_value, 0)) AS tp,
                 SUM(COALESCE(s.net_sale_value, 0)) AS net,
                 SUM(COALESCE(s.units, 0)) AS units,
                 SUM(COALESCE(s.net_wo_reg_disc_value, 0)) AS net_wo_reg,
                 SUM(COALESCE(s.cyp, 0)) AS cyp,
                 COUNT(DISTINCT s.position_code) FILTER (WHERE s.positive_sale_rows > 0) AS active_positions,
                 SUM(COALESCE(s.negative_net_sale_abs, 0)) AS returns,
                 SUM(COALESCE(s.positive_net_sale_value, 0)) AS positive_sales,
                 SUM(COALESCE(s.positive_tp_sale_value, 0)) AS positive_tp,
                 SUM(COALESCE(s.bonus_discount, 0)) AS bonus_discount
          FROM public.sales_monthly_position_summary s
          WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month = %s AND s.fiscal_year = %s AND {summary_team}
        ), customers AS (
          SELECT COUNT(DISTINCT s.cust_number) FILTER (WHERE s.has_positive_sale) AS active_customers,
                 COUNT(DISTINCT s.cust_number) AS transacting_customers
          FROM public.sales_monthly_customer_summary s
          WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month = %s AND s.fiscal_year = %s AND {summary_team}
        ) SELECT a.tp, a.net, a.units, a.net_wo_reg, a.cyp,
                 c.active_customers, a.active_positions, a.returns, a.positive_sales,
                 a.positive_tp, a.bonus_discount, c.transacting_customers
          FROM actual a CROSS JOIN customers c"""
        sales_params = cte_params + [sales_month, fy, sales_month, fy]
        prev_sql = f"""{cte}, actual AS (
          SELECT SUM(COALESCE(s.net_wo_reg_disc_value, 0)) AS net_wo_reg,
                 SUM(COALESCE(s.units, 0)) AS units,
                 SUM(COALESCE(s.negative_net_sale_abs, 0)) AS returns,
                 SUM(COALESCE(s.positive_tp_sale_value, 0)) AS positive_tp,
                 SUM(COALESCE(s.{summary_metric}, 0)) AS selected_metric
          FROM public.sales_monthly_position_summary s
          WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month = %s AND s.fiscal_year = %s AND {summary_team}
        ), customers AS (
          SELECT COUNT(DISTINCT s.cust_number) FILTER (WHERE s.has_positive_sale) AS active_customers
          FROM public.sales_monthly_customer_summary s
          WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month = %s AND s.fiscal_year = %s AND {summary_team}
        ) SELECT a.net_wo_reg, a.units, c.active_customers, a.returns,
                 a.positive_tp, a.selected_metric
          FROM actual a CROSS JOIN customers c"""
        prev_params = cte_params + [prev_month, fy, prev_month, fy]
    else:
        sales_params = cte_params + [sales_month, fy]
        prev_params = cte_params + [prev_month, fy]
    if not use_summaries:
        prev_sql = f"""{cte}
          SELECT SUM({num('net_wo_reg_disc_value')}), SUM({num('e_qty')}),
                 COUNT(DISTINCT cust_number) FILTER (WHERE {num('net_sale_value')} > 0),
                 SUM(ABS({num('net_sale_value')})) FILTER (WHERE {num('net_sale_value')} < 0),
                 SUM({num('tp_sale_value')}) FILTER (WHERE {num('tp_sale_value')} > 0),
                 SUM({num(sales_column)})
          FROM sales_data WHERE position_code IN (SELECT position_code FROM scope)
            AND reporting_month = %s AND fiscal_year = %s"""
    lower_levels = {"HOD": ("RSM",), "RSM": ("ASM",), "ASM": ("SPO", "MIO")}
    lower_actual = lower_total = 0
    if designation in lower_levels:
        recursive_cte = cte if cte.startswith("WITH RECURSIVE ") else cte.replace("WITH ", "WITH RECURSIVE ", 1)
        lower_sql = f"""{recursive_cte}, lower_tree AS (
          SELECT m.position_code AS root_code, m.position_code AS child_code
          FROM staff_master m
          WHERE m.position_code IN (SELECT position_code FROM scope)
            AND m.designation_name = ANY(%s)
          UNION
          SELECT t.root_code, child.position_code
          FROM lower_tree t
          JOIN staff_master child ON child.report_to_position_code = t.child_code
          JOIN scope child_scope ON child_scope.position_code = child.position_code
          ), selling_positions AS (
          SELECT DISTINCT position_code FROM {('public.sales_monthly_position_summary' if use_summaries else 'sales_data')}
          WHERE reporting_month = %s AND fiscal_year = %s
            AND {('positive_sale_rows > 0' if use_summaries else num('net_sale_value') + ' > 0')}
            {('AND ' + team_predicate('team', team)) if use_summaries else ''})
          SELECT COUNT(DISTINCT root_code),
                 COUNT(DISTINCT root_code) FILTER (WHERE sp.position_code IS NOT NULL)
          FROM lower_tree t
          LEFT JOIN selling_positions sp ON sp.position_code = t.child_code"""

    # First-ever positive sale by customer, constrained to the selected field-force scope.
    first_sql = f"""{cte}, first_buy AS (
      SELECT cust_number, MIN(reporting_month) AS first_month
      FROM {('public.sales_monthly_customer_summary' if use_summaries else 'sales_data')}
      WHERE position_code IN (SELECT position_code FROM scope)
        AND {('has_positive_sale' if use_summaries else num('net_sale_value') + ' > 0')}
        {('AND ' + team_predicate('team', team)) if use_summaries else ''}
      GROUP BY cust_number)
      SELECT COUNT(*) FROM first_buy WHERE first_month = %s"""
    # These aggregates are independent. Run them together so one slow scan
    # does not delay the start of every other KPI query.
    with ThreadPoolExecutor(max_workers=4) as executor:
        sales_future = submit_query(executor, "kpis.sales_summary" if use_summaries else "kpis.sales", sales_sql, sales_params)
        prev_future = submit_query(executor, "kpis.previous_summary" if use_summaries else "kpis.previous", prev_sql, prev_params)
        first_future = submit_query(executor, "kpis.first_buy", first_sql, cte_params + [sales_month])
        lower_future = (submit_query(executor, "kpis.lower_staff", lower_sql,
                         cte_params + [list(lower_levels[designation]), sales_month, fy])
                        if designation in lower_levels else None)
        s = [float(x or 0) for x in sales_future.result()[0]]
        prev = [float(x or 0) for x in prev_future.result()[0]]
        first_time = float(first_future.result()[0][0] or 0)
        if lower_future:
            lower_total, lower_actual = (int(x or 0) for x in lower_future.result()[0])

    # ---- targets (target_data) ------------------------------------------
    t = [0.0] * 7
    if fy == TARGET_FY:
        tgt_sql = f"""{cte}
          SELECT SUM(tgt_tp_value_{sfx}), SUM(tgt_net_w_reg_{sfx}), SUM(tgt_unit_{sfx}),
                 SUM(tgt_net_wo_reg_{sfx}), SUM(tgt_cyps_{sfx}),
                 SUM(COALESCE(tgt_add_disc_value_{sfx},0)),
                 SUM(COALESCE(tgt_reg_disc_value_{sfx},0))
          FROM target_data
          WHERE position_code_2026_27 IN (SELECT position_code FROM scope)"""
        t = [float(x or 0) for x in query(tgt_sql, cte_params)[0]]

    # Calculate MIO and SPO separately; combining these distinct counts into
    # the headline aggregate increased execution time in read-only plans.
    cur_sales_source = "public.sales_monthly_position_summary" if use_summaries else "sales_data"
    cur_positive = "s.positive_sale_rows > 0" if use_summaries else f"{num('s.net_sale_value')} > 0"
    cur_team_filter = f"AND {team_predicate('s.team', team)}" if use_summaries else ""
    cur_res = query(f"""{cte}
      SELECT
        COUNT(DISTINCT CASE WHEN m.designation_name = 'MIO' AND {cur_positive} THEN s.position_code END),
        COUNT(DISTINCT CASE WHEN m.designation_name = 'SPO' AND {cur_positive} THEN s.position_code END)
      FROM {cur_sales_source} s
      JOIN staff_master m ON m.position_code = s.position_code
      WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month = %s AND s.fiscal_year = %s {cur_team_filter}""", cte_params + [sales_month, fy])[0]
    mio_act, spo_act = float(cur_res[0] or 0), float(cur_res[1] or 0)

    tgt_counts = query(f"""{cte}
      SELECT
        COUNT(CASE WHEN designation_name = 'MIO' THEN 1 END),
        COUNT(CASE WHEN designation_name = 'SPO' THEN 1 END)
      FROM staff_master
      WHERE position_code IN (SELECT position_code FROM scope)""", cte_params)[0]
    mio_tgt, spo_tgt = float(tgt_counts[0] or 0), float(tgt_counts[1] or 0)

    head = int(tgt_counts[0] or 0) + int(tgt_counts[1] or 0)
    team_sales_source = "public.sales_monthly_position_summary" if use_summaries else "sales_data"
    team_sales_filter = f"WHERE {team_predicate('team', team)} AND" if use_summaries else "WHERE"
    team_name = query(f"""{cte}, scoped_teams AS (
        SELECT CASE WHEN {team_predicate('team', 'FMCG')} THEN 'FMCG' ELSE 'PHARMA' END AS label
        FROM {team_sales_source} {team_sales_filter} position_code IN (SELECT position_code FROM scope)
        UNION
        SELECT CASE WHEN {team_predicate('team', 'FMCG')} THEN 'FMCG' ELSE 'PHARMA' END AS label
        FROM target_data WHERE position_code_2026_27 IN (SELECT position_code FROM scope)
      ) SELECT COALESCE(string_agg(label, ', ' ORDER BY label), '') FROM scoped_teams""",
      cte_params)[0][0]

    def pair(actual, target):
        return {"actual": actual, "target": target,
                "ach": round(actual / target * 100, 1) if target else None}

    tp, net, units, wo, cyp, shops, active_pos, ret, pos_sales, pos_gross, bonus_discount, transacting_shops = s
    disc_actual = tp - net  # additional + regular discount actually given

    spo_sections = {}
    if designation == "ASM":
        # The manager hierarchy panel below replaces this list when targets
        # are available. For other fiscal years it remains empty.
        spo_sections = {"hierarchy_label": "SPO", "hierarchy_performance": []}
        # Sections 2 and 3 use each ASM's direct field reports, whether they
        # are SPOs or MIOs. Active shops are distinct customers with positive
        # net sales during the selected reporting month.
        if use_summaries:
            person_source = "public.sales_monthly_position_summary"
            person_selected = f"COALESCE(s.{summary_metric}, 0)"
            person_net = "COALESCE(s.net_sale_value, 0)"
            person_tp = "COALESCE(s.gross_tp_value, 0)"
            person_commission = "COALESCE(s.mnp_commission, 0)"
            person_team_filter = f"AND {team_predicate('s.team', team)}"
            customer_cte = f""", customer_by_person AS (
              SELECT s.position_code,
                     COUNT(DISTINCT s.cust_number) FILTER (WHERE s.has_positive_sale) AS active_shops
              FROM public.sales_monthly_customer_summary s
              WHERE s.position_code IN (SELECT position_code FROM child_force)
                AND s.reporting_month = %s AND s.fiscal_year = %s
                AND {team_predicate('s.team', team)}
              GROUP BY s.position_code)"""
            customer_join = "LEFT JOIN customer_by_person customer ON customer.position_code = c.position_code"
            active_shops_expr = "COALESCE(customer.active_shops, 0)"
            person_params = cte_params + [sales_month, fy, sales_month, fy]
        else:
            person_source = "sales_data"
            person_selected = num('s.' + sales_column)
            person_net = num('s.net_sale_value')
            person_tp = num('s.tp_sale_value')
            person_commission = num('s.mnp_commission')
            person_team_filter = ""
            customer_cte = ""
            customer_join = ""
            active_shops_expr = "COALESCE(a.active_shops, 0)"
            person_params = cte_params + [sales_month, fy]
        team_rows = query(f"""{cte}, child_force AS (
          SELECT m.position_code, MAX(m.employee_name) AS employee_name,
                 MAX(m.designation_name) AS designation_name
          FROM staff_master m
          JOIN scope parent_scope ON m.report_to_position_code = parent_scope.position_code
          JOIN scope child_scope ON child_scope.position_code = m.position_code
          JOIN staff_master parent ON parent.position_code = parent_scope.position_code
          WHERE parent.designation_name = 'ASM'
            AND m.designation_name IN ('SPO', 'MIO')
          GROUP BY m.position_code), actual_by_person AS (
          SELECT s.position_code,
                 SUM({person_selected}) AS actual_sales,
                 SUM({person_net}) AS actual_net_sales,
                 SUM({person_tp}) AS actual_tp,
                 SUM({person_commission}) AS commission
                 {'' if use_summaries else ", COUNT(DISTINCT s.cust_number) FILTER (WHERE " + num('s.net_sale_value') + " > 0) AS active_shops"}
          FROM {person_source} s
          WHERE s.position_code IN (SELECT position_code FROM child_force)
            AND s.reporting_month = %s AND s.fiscal_year = %s
            {person_team_filter}
          GROUP BY s.position_code), target_by_person AS (
          SELECT position_code_2026_27 AS position_code,
                 SUM(COALESCE({target_prefix}_{sfx}, 0)) AS target_sales,
                 SUM(COALESCE(tgt_tp_value_{sfx}, 0)) AS target_tp,
                 SUM(COALESCE(tgt_add_disc_value_{sfx}, 0) + COALESCE(tgt_reg_disc_value_{sfx}, 0)) AS discount_budget
          FROM target_data
          WHERE position_code_2026_27 IN (SELECT position_code FROM child_force)
          GROUP BY position_code_2026_27){customer_cte}
          SELECT c.position_code, c.employee_name, c.designation_name,
                 {active_shops_expr}, COALESCE(a.actual_sales, 0),
                 COALESCE(t.target_sales, 0), COALESCE(a.actual_tp, 0),
                 COALESCE(t.target_tp, 0), COALESCE(t.discount_budget, 0),
                 COALESCE(a.commission, 0), COALESCE(a.actual_net_sales, 0)
          FROM child_force c
          LEFT JOIN actual_by_person a ON a.position_code = c.position_code
          LEFT JOIN target_by_person t ON t.position_code = c.position_code
          {customer_join}
          ORDER BY {active_shops_expr} DESC, c.employee_name""",
          person_params) if fy == TARGET_FY else []

        team_performance = []
        for r in team_rows:
            actual_sales, target_sales = float(r[4] or 0), float(r[5] or 0)
            team_performance.append({
                "position_code": r[0], "employee": r[1] or "Unknown employee",
                "designation": r[2] or "", "active_shops": int(r[3] or 0),
                "actual_sales": actual_sales, "target_sales": target_sales,
                "achievement_pct": round(actual_sales / target_sales * 100, 1) if target_sales else None,
                "actual_tp": float(r[6] or 0), "target_tp": float(r[7] or 0),
                "discount_budget": float(r[8] or 0), "commission": float(r[9] or 0),
                "actual_net_sales": float(r[10] or 0),
            })

        team_actual_tp = sum(x["actual_tp"] for x in team_performance)
        team_target_tp = sum(x["target_tp"] for x in team_performance)
        team_actual_sales = sum(x["actual_net_sales"] for x in team_performance)
        team_target_sales = sum(x["target_sales"] for x in team_performance)
        team_discount_budget = sum(x["discount_budget"] for x in team_performance)
        team_discount_actual = team_actual_tp - team_actual_sales
        team_actual_discount_pct = team_discount_actual / team_actual_tp * 100 if team_actual_tp else None
        team_budget_discount_pct = team_discount_budget / team_target_tp * 100 if team_target_tp else None

        critical_source = "public.sales_monthly_position_product_summary" if use_summaries else "sales_data"
        critical_metric = f"COALESCE({SUMMARY_METRICS[sales_column]}, 0)" if use_summaries else num(sales_column)
        critical_team_filter = f"AND {team_predicate('team', team)}" if use_summaries else ""
        critical_skus = query(f"""{cte}, child_force AS (
          SELECT m.position_code
          FROM staff_master m
          JOIN scope parent_scope ON m.report_to_position_code = parent_scope.position_code
          JOIN scope child_scope ON child_scope.position_code = m.position_code
          JOIN staff_master parent ON parent.position_code = parent_scope.position_code
          WHERE parent.designation_name = 'ASM'
            AND m.designation_name IN ('SPO', 'MIO')
          GROUP BY m.position_code), product_targets AS (
          SELECT product_group_on_master AS group_on, SUM(COALESCE({target_prefix}_{sfx}, 0)) AS target_sales
          FROM target_data
          WHERE position_code_2026_27 IN (SELECT position_code FROM child_force)
            AND product_group_on_master IS NOT NULL
          GROUP BY product_group_on_master), product_actuals AS (
          SELECT group_on, SUM({critical_metric}) AS actual_sales
          FROM {critical_source}
          WHERE position_code IN (SELECT position_code FROM child_force)
            AND reporting_month = %s AND fiscal_year = %s
            AND group_on IS NOT NULL
            {critical_team_filter}
          GROUP BY group_on)
          SELECT COUNT(*) FROM product_targets t
          LEFT JOIN product_actuals a ON a.group_on = t.group_on
          WHERE t.target_sales > 0 AND COALESCE(a.actual_sales, 0) / t.target_sales < 0.5""",
          cte_params + [sales_month, fy])[0][0] if fy == TARGET_FY else 0
        spo_sections["team_summary"] = {
            "member_count": len(team_performance),
            "performing_count": sum(x["achievement_pct"] is not None and x["achievement_pct"] >= 100 for x in team_performance),
            "below_50_count": sum(x["achievement_pct"] is not None and x["achievement_pct"] < 50 for x in team_performance),
            "critical_sku_count": int(critical_skus or 0),
            "actual_discount_value": team_discount_actual,
            "actual_discount_pct": round(team_actual_discount_pct, 1) if team_actual_discount_pct is not None else None,
            "budget_discount_pct": round(team_budget_discount_pct, 1) if team_budget_discount_pct is not None else None,
            "discount_variance_pp": round(team_budget_discount_pct - team_actual_discount_pct, 1) if team_budget_discount_pct is not None and team_actual_discount_pct is not None else None,
            "commission": sum(x["commission"] for x in team_performance),
            "net_sales": team_actual_sales,
        }

    # Team-scoped product achievement data is used by section 4 for every
    # management designation, and by the existing SKU panel for SPO/MIO.
    sales_team_filter = ""
    # SKU performance is grouped by GROUP_ON, which is the common SKU key
    # across sales_data and target_data.product_group_on_master.
    target_team_filter = ""
    if team == "FMCG":
        sales_team_filter = "AND UPPER(COALESCE(s.team, '')) LIKE 'FAST MOVING CONSUMER GOODS%%'"
        target_team_filter = "AND UPPER(COALESCE(td.team, '')) LIKE 'FAST MOVING CONSUMER GOODS%%'"
    elif team == "PHARMA":
        sales_team_filter = "AND UPPER(COALESCE(s.team, '')) LIKE 'PHARMACEUTICAL%%'"
        target_team_filter = "AND UPPER(COALESCE(td.team, '')) LIKE 'PHARMACEUTICAL%%'"
    product_source = "public.sales_monthly_position_product_summary" if use_summaries else "sales_data"
    product_metric = f"COALESCE(s.{summary_metric}, 0)" if use_summaries else num('s.' + sales_column)
    product_tp = "COALESCE(s.gross_tp_value, 0)" if use_summaries else num('s.tp_sale_value')
    product_net = "COALESCE(s.net_sale_value, 0)" if use_summaries else num('s.net_sale_value')

    product_rows = query(f"""{cte}, target_by_product AS (
      SELECT td.product_group_on_master AS group_on,
             SUM(COALESCE(td.{target_prefix}_{sfx}, 0)) AS target_net_sales
      FROM target_data td
      WHERE td.position_code_2026_27 IN (SELECT position_code FROM scope)
        AND td.product_group_on_master IS NOT NULL
        {target_team_filter}
      GROUP BY td.product_group_on_master), sales_by_product AS (
      SELECT s.group_on, MAX(s.group_on) AS product_name,
             SUM({product_metric}) AS actual_net_sales,
             COALESCE(MAX(NULLIF(s.prd_name, '')), MAX(s.group_on)) AS discount_product_name,
             SUM({product_tp}) AS tp_value,
             SUM({product_net}) AS net_value,
             SUM({product_tp}) - SUM({product_net}) AS discount_value
      FROM {product_source} s
      WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month = %s AND s.fiscal_year = %s
        AND s.group_on IS NOT NULL
        {sales_team_filter}
      GROUP BY s.group_on), products AS (
      SELECT group_on FROM target_by_product
      UNION
      SELECT group_on FROM sales_by_product), product_values AS (
      SELECT p.group_on, COALESCE(s.product_name, p.group_on) AS product_name,
             COALESCE(s.actual_net_sales, 0) AS actual_net_sales,
             COALESCE(t.target_net_sales, 0) AS target_net_sales,
             s.discount_product_name, s.tp_value, s.net_value, s.discount_value
      FROM products p
      LEFT JOIN sales_by_product s ON s.group_on = p.group_on
      LEFT JOIN target_by_product t ON t.group_on = p.group_on), ranked_products AS (
      SELECT v.*,
             ROW_NUMBER() OVER (ORDER BY
               CASE WHEN actual_net_sales > 0 AND target_net_sales <> 0
                    THEN actual_net_sales / target_net_sales END ASC NULLS LAST,
               actual_net_sales DESC, group_on) AS achievement_bottom_rank,
             ROW_NUMBER() OVER (ORDER BY
               CASE WHEN actual_net_sales > 0 AND target_net_sales <> 0
                    THEN actual_net_sales / target_net_sales END DESC NULLS LAST,
               actual_net_sales DESC, group_on) AS achievement_top_rank,
             ROW_NUMBER() OVER (ORDER BY
               CASE WHEN tp_value > 0 AND discount_value > 0
                    THEN discount_value / tp_value END ASC NULLS LAST, group_on) AS discount_bottom_rank,
             ROW_NUMBER() OVER (ORDER BY
               CASE WHEN tp_value > 0 AND discount_value > 0
                    THEN discount_value / tp_value END DESC NULLS LAST, group_on) AS discount_top_rank
      FROM product_values v)
      SELECT group_on, product_name, actual_net_sales, target_net_sales,
             discount_product_name, tp_value, net_value, discount_value
      FROM ranked_products
      WHERE achievement_bottom_rank <= 10 OR achievement_top_rank <= 10
         OR discount_bottom_rank <= 10 OR discount_top_rank <= 10
      ORDER BY actual_net_sales DESC NULLS LAST""",
      cte_params + [sales_month, fy]) if fy == TARGET_FY else []
    product_performance = [
        {"group_on": r[0], "product_no": r[0], "prd_name": r[1] or r[0],
         "actual_net_sales": float(r[2] or 0), "target_net_sales": float(r[3] or 0),
         "achievement_pct": round(float(r[2] or 0) / float(r[3]) * 100, 1) if r[3] else None}
        for r in product_rows if float(r[2] or 0) > 0
    ]
    ranked_products = sorted(
        (r for r in product_performance if r["achievement_pct"] is not None),
        key=lambda r: r["achievement_pct"],
    )
    # The UI offers Top 10 / Bottom 10 only; cap the payload to both sets.
    product_performance = list({
        r["group_on"]: r for r in ranked_products[:10] + ranked_products[-10:]
    }.values())

    # Product-level discount is the same basis as the headline discount KPI:
    # TP value minus net sale value, expressed as a percentage of TP value.
    # The former grouped discount query returned product keys in order. Keep
    # that order so equal discount percentages retain their panel ordering.
    discount_product_rows = (
        sorted(((r[0], r[4], r[5], r[6], r[7]) for r in product_rows
                if r[5] is not None and r[5] > 0 and r[7] is not None and r[7] > 0),
               key=lambda r: r[0])
        if fy == TARGET_FY else query(f"""{cte}
      SELECT s.group_on,
             COALESCE(MAX(NULLIF(s.prd_name, '')), MAX(s.group_on)) AS product_name,
             SUM({product_tp}) AS tp_value,
             SUM({product_net}) AS net_value,
             SUM({product_tp}) - SUM({product_net}) AS discount_value
      FROM {product_source} s
      WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month = %s AND s.fiscal_year = %s
        AND s.group_on IS NOT NULL
        {sales_team_filter}
      GROUP BY s.group_on
      HAVING SUM({product_tp}) > 0
         AND SUM({product_tp}) - SUM({product_net}) > 0""",
      cte_params + [sales_month, fy])
    )
    discount_products = [
        {"group_on": r[0], "prd_name": r[1] or r[0],
         "tp_value": float(r[2] or 0), "net_value": float(r[3] or 0),
         "discount_value": float(r[4] or 0),
         "discount_pct": round(float(r[4] or 0) / float(r[2]) * 100, 1) if r[2] else None}
        for r in discount_product_rows
    ]
    ranked_discount_products = sorted(
        (r for r in discount_products if r["discount_pct"] is not None),
        key=lambda r: r["discount_pct"],
    )
    discount_products = list({
        r["group_on"]: r for r in ranked_discount_products[:10] + ranked_discount_products[-10:]
    }.values())
    # These panels are scope-based and should also work for ALL/management
    # views, not only when an individual SPO or MIO designation is selected.
    customer_source = "public.sales_monthly_customer_summary" if use_summaries else "sales_data"
    customer_metric = f"COALESCE({SUMMARY_METRICS[sales_column]}, 0)" if use_summaries else num(sales_column)
    customer_team_filter = f"AND {team_predicate('team', team)}" if use_summaries else ""
    customer_rows = query(f"""{cte}, customer_sales AS (
      SELECT cust_name, cust_number, SUM({customer_metric}) AS net_sales
      FROM {customer_source}
      WHERE position_code IN (SELECT position_code FROM scope)
        AND reporting_month = %s AND fiscal_year = %s
        {customer_team_filter}
      GROUP BY cust_name, cust_number
      HAVING SUM({customer_metric}) > 0), ranked_customers AS (
      SELECT cust_name, cust_number, net_sales,
             ROW_NUMBER() OVER (ORDER BY net_sales DESC) AS top_rank,
                ROW_NUMBER() OVER (ORDER BY net_sales ASC) AS bottom_rank
      FROM customer_sales)
      SELECT cust_name, cust_number, net_sales, top_rank, bottom_rank
      FROM ranked_customers WHERE top_rank <= 10 OR bottom_rank <= 10
      ORDER BY net_sales DESC""", cte_params + [sales_month, fy])
    spo_sections["top_customers"] = [
        {"cust_name": r[0], "cust_number": r[1], "net_sales": float(r[2] or 0)}
        for r in customer_rows if r[3] <= 10
    ]
    spo_sections["bottom_customers"] = sorted([
        {"cust_name": r[0], "cust_number": r[1], "net_sales": float(r[2] or 0)}
        for r in customer_rows if r[4] <= 10
    ], key=lambda r: r["net_sales"])
    # A customer's percentage is its share of positive sales. Customer-level
    # targets do not exist, so this is never called target achievement.
    all_positive_sales = pos_sales
    all_positive_sales = pos_sales
    for customer in spo_sections["top_customers"] + spo_sections["bottom_customers"]:
        customer["performance_pct"] = round(max(0, customer["net_sales"]) / all_positive_sales * 100, 1) if all_positive_sales > 0 else None

    # Call/activity data currently exists for FMCG only. It is scoped through
    # the same staff hierarchy as the sales dashboard so employee and territory
    # filters continue to apply without a separate filter system.
    call_data = {"available": team != "PHARMA", "manager_days": [], "shops": [],
                 "outcomes": {"accepted": 0, "rejected": 0, "shop_closed": 0, "total": 0}}
    if team != "PHARMA":
        manager_sql = f"""{cte}
          SELECT COALESCE(NULLIF(TRIM(c.manager), ''), 'Unassigned') AS manager,
                 COALESCE(NULLIF(TRIM(c.ff_name), ''), sm.employee_name, c.position_code) AS employee,
                 c.position_code,
                 COUNT(DISTINCT c.call_date) AS call_days,
                 SUM(c.calls) AS calls
          FROM call_data_rollup c
          JOIN staff_master sm ON sm.position_code = c.position_code
          WHERE c.kind = 'manager_day'
            AND c.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)
            AND UPPER(TRIM(sm.designation_name)) = 'SPO'
          GROUP BY c.manager, c.ff_name, sm.employee_name, c.position_code
          ORDER BY call_days DESC, calls DESC, employee
          LIMIT 10"""
        shops_sql = f"""{cte}, shop_counts AS (
          SELECT c.customer_name, SUM(c.calls) AS calls
          FROM call_data_rollup c
          WHERE c.kind = 'shop_month'
            AND c.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)
          GROUP BY c.customer_name
        ), candidates AS (
          SELECT customer_name, calls FROM shop_counts
          ORDER BY calls DESC FETCH FIRST 10 ROWS WITH TIES
        ), day_counts AS (
          SELECT d.customer_name, COUNT(DISTINCT d.call_date) AS call_days
          FROM call_data_rollup d
          JOIN candidates top ON d.customer_name IS NOT DISTINCT FROM top.customer_name
          WHERE d.kind = 'shop_day'
            AND d.position_code IN (SELECT position_code FROM scope)
            AND d.month = ANY(%s)
          GROUP BY d.customer_name
        )
        SELECT COALESCE(NULLIF(TRIM(top.customer_name), ''), 'Unknown shop') AS customer_name,
               top.calls, COALESCE(days.call_days, 0)
        FROM candidates top
        LEFT JOIN day_counts days ON days.customer_name IS NOT DISTINCT FROM top.customer_name
        ORDER BY top.calls DESC, days.call_days DESC, customer_name
        LIMIT 10"""
        outcomes_sql = f"""{cte}
          SELECT COALESCE(SUM(c.accepted), 0), COALESCE(SUM(c.rejected), 0),
                 COALESCE(SUM(c.shop_closed), 0), COALESCE(SUM(c.calls), 0)
          FROM call_data_rollup c
          WHERE c.kind = 'outcome'
            AND c.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)
          """
        call_params = cte_params + [call_months]
        with ThreadPoolExecutor(max_workers=3) as executor:
            manager_future = submit_query(executor, "kpis.call_managers", manager_sql, call_params)
            shops_future = submit_query(executor, "kpis.call_shops", shops_sql, cte_params + [call_months, call_months])
            outcomes_future = submit_query(executor, "kpis.call_outcomes", outcomes_sql, call_params)
            manager_call_rows = manager_future.result()
            shop_call_rows = shops_future.result()
            outcome_row = outcomes_future.result()[0]
        call_data["manager_days"] = [
            {"manager": r[0], "employee": r[1], "position_code": r[2],
             "call_days": int(r[3] or 0), "calls": int(r[4] or 0)}
            for r in manager_call_rows
        ]
        call_data["shops"] = [
            {"customer_name": r[0], "calls": int(r[1] or 0), "call_days": int(r[2] or 0)}
            for r in shop_call_rows
        ]
        call_data["outcomes"] = {
            "accepted": int(outcome_row[0] or 0), "rejected": int(outcome_row[1] or 0),
            "shop_closed": int(outcome_row[2] or 0), "total": int(outcome_row[3] or 0),
        }

    manager_roles = {
        "ALL": ("RSM", "ASM", "SPO", "PS", "SB", "MIO", "ASMTE", "CM", "SPOWS", "TE"),
        "EXEC": ("RSM", "ASM", "SPO", "PS", "SB", "MIO", "ASMTE", "CM", "SPOWS", "TE"),
        "HOD": ("RSM", "ASM", "SPO", "PS", "SB", "MIO", "ASMTE", "CM", "SPOWS", "TE"),
        "DGM": ("RSM", "ASM", "SPO", "PS", "SB", "MIO", "ASMTE", "CM", "SPOWS", "TE"),
        "RSM": ("ASM",),
        "ASM": ("SPO", "PS", "SB", "MIO", "ASMTE", "CM", "SPOWS", "TE"),
    }
    hierarchy_total = 0
    hierarchy_active = 0
    if designation in manager_roles and fy == TARGET_FY:
        recursive_cte = cte if cte.startswith("WITH RECURSIVE ") else cte.replace("WITH ", "WITH RECURSIVE ", 1)
        manager_source = "public.sales_monthly_position_summary" if use_summaries else "sales_data"
        manager_metric = f"COALESCE({summary_metric}, 0)" if use_summaries else num(sales_column)
        manager_team_filter = f"AND {team_predicate('team', team)}" if use_summaries else ""
        team_rows = query(f"""{recursive_cte}, roots AS (
          SELECT DISTINCT m.position_code, m.employee_name, m.designation_name
          FROM staff_master m WHERE m.position_code IN (SELECT position_code FROM scope)
            AND m.designation_name = ANY(%s)
        ), tree AS (
          SELECT r.position_code AS root_code, r.position_code AS child_code FROM roots r
          UNION
          SELECT t.root_code, m.position_code FROM tree t
          JOIN staff_master m ON m.report_to_position_code = t.child_code
          WHERE m.position_code IN (SELECT position_code FROM scope)
        ), actuals AS (
          SELECT position_code, SUM({manager_metric}) AS actual FROM {manager_source}
          WHERE position_code IN (SELECT position_code FROM scope)
            AND reporting_month = %s AND fiscal_year = %s {manager_team_filter} GROUP BY position_code
        ), targets AS (
          SELECT position_code_2026_27 AS position_code, SUM({target_prefix}_{sfx}) AS target
          FROM target_data WHERE position_code_2026_27 IN (SELECT position_code FROM scope)
          GROUP BY position_code_2026_27
        ), performance AS (
          SELECT r.position_code, r.employee_name, r.designation_name,
                 SUM(COALESCE(a.actual, 0)) AS actual,
                 SUM(COALESCE(g.target, 0)) AS target
          FROM roots r JOIN tree t ON t.root_code = r.position_code
          LEFT JOIN actuals a ON a.position_code = t.child_code
          LEFT JOIN targets g ON g.position_code = t.child_code
          GROUP BY r.position_code, r.employee_name, r.designation_name
        ), ranked AS (
          SELECT p.*,
                 ROW_NUMBER() OVER (
                   PARTITION BY designation_name
                   ORDER BY actual / NULLIF(target, 0) ASC NULLS LAST, position_code
                 ) AS role_bottom_rank,
                 ROW_NUMBER() OVER (
                   PARTITION BY designation_name
                   ORDER BY actual / NULLIF(target, 0) DESC NULLS LAST, position_code
                 ) AS role_top_rank,
                 ROW_NUMBER() OVER (
                   ORDER BY actual / NULLIF(target, 0) ASC NULLS LAST, position_code
                 ) AS all_bottom_rank,
                 ROW_NUMBER() OVER (
                   ORDER BY actual / NULLIF(target, 0) DESC NULLS LAST, position_code
                 ) AS all_top_rank,
                 COUNT(*) OVER () AS total_count,
                 COUNT(*) FILTER (WHERE actual > 0) OVER () AS active_count
          FROM performance p
        )
        SELECT position_code, employee_name, designation_name, actual, target,
               total_count, active_count
        FROM ranked
        WHERE role_bottom_rank <= 10 OR role_top_rank <= 10
           OR all_bottom_rank <= 10 OR all_top_rank <= 10
        ORDER BY position_code""",
          cte_params + [list(manager_roles[designation]), sales_month, fy])
        hierarchy_total = int(team_rows[0][5] or 0) if team_rows else 0
        hierarchy_active = int(team_rows[0][6] or 0) if team_rows else 0
        spo_sections["hierarchy_performance"] = [
            {"position_code": code, "employee": name or code, "designation": role,
             "actual": float(actual or 0), "target": float(target or 0),
             "achievement_pct": round(float(actual or 0) / float(target) * 100, 1) if target else None}
            for code, name, role, actual, target, _, _ in team_rows
        ]
        spo_sections["hierarchy_label"] = " / ".join(manager_roles[designation])

    spo_sections["product_performance"] = product_performance
    spo_sections["discount_products"] = discount_products
    spo_sections["call_data"] = call_data

    # Header identity for an individual field-force view. Keep this separate
    # from the sales scope so the visible header describes the selected person,
    # not every lower-level position included in an aggregate.
    header_position_code = ""
    header_region, header_zone, header_subzone = region, zone, subzone
    header_department, header_territory = "", ""
    if employee and employee != "All":
        header_rows = query("""
          SELECT position_code, region_name, zone_name, sub_zone, department_name, dept_territory_code, team_name
          FROM staff_master
          WHERE LOWER(TRIM(employee_name)) = LOWER(%s)
          ORDER BY position_code
          LIMIT 1""", [employee.strip()])
        if header_rows:
            header_position_code, header_region, header_zone, header_subzone, header_dept_name, header_dept_terr, header_team = header_rows[0]
            header_territory = header_dept_terr or header_position_code or ""
            if header_position_code and '-' in header_position_code:
                parts = header_position_code.split('-')
                if len(parts) >= 2 and parts[1]:
                    header_department = parts[1]
            if not header_department:
                t_str = (header_team or team_name or "").upper()
                header_department = "PHR" if "PHARM" in t_str else "FMCG" if "FMCG" in t_str or "FAST" in t_str else (header_dept_name or "")
    elif territory and territory != "All":
        header_rows = query("""
          SELECT position_code, region_name, zone_name, sub_zone, department_name, dept_territory_code, team_name
          FROM staff_master
          WHERE TRIM(dept_territory_code) = %s OR TRIM(position_code) = %s
          ORDER BY position_code
          LIMIT 1""", [territory.strip(), territory.strip()])
        if header_rows:
            header_position_code, header_region, header_zone, header_subzone, header_dept_name, header_dept_terr, header_team = header_rows[0]
            header_territory = header_dept_terr or header_position_code or territory
            if header_position_code and '-' in header_position_code:
                parts = header_position_code.split('-')
                if len(parts) >= 2 and parts[1]:
                    header_department = parts[1]
            if not header_department:
                t_str = (header_team or team_name or "").upper()
                header_department = "PHR" if "PHARM" in t_str else "FMCG" if "FMCG" in t_str or "FAST" in t_str else (header_dept_name or "")

    if not header_department:
        t_str = (team or team_name or "").upper()
        header_department = "PHR" if "PHARM" in t_str else "FMCG" if "FMCG" in t_str or "FAST" in t_str else ""

    return {
        "meta": {
            "designation": designation, "region": region, "zone": zone,
            "subzone": subzone, "territory": territory, "employee": employee, "team": team_name,
            "position_code": header_position_code or "",
            "dept_territory_code": header_territory or (territory if territory != "All" else ""),
            "department": header_department or "",
            "header_region": header_region or region,
            "header_zone": header_zone or zone,
            "header_subzone": header_subzone or subzone,
            "scope_mode": scope_mode(designation),
            "month": month, "fy": fy, "team_filter": team,
            "value_metric": value_metric, "value_metric_label": metric_label,
            "targets_available": fy == TARGET_FY
        },
        "gross_tp": pair(tp, t[0]),
        "net_sales": pair(wo, t[3]),
        "net_sales_value": pair(s[sales_index], t[target_index]),
        "golm": round((s[sales_index] - prev[5]) / abs(prev[5]) * 100, 1) if prev[5] else None,
        "golm_previous_value": prev[5],
        "active_lower_staff": pair(lower_actual, lower_total),
        "units": pair(units, t[2]),
        "net_wo_reg": pair(net, t[1]),
        "cyp": pair(cyp, t[4]),
        "discount": {
            "actual": disc_actual, "budget": t[5] + t[6],
            "bonus_discount": bonus_discount,
            "regular_discount": wo - net,
            "budget_additional_discount": t[5],
            "budget_regular_discount": t[6],
            "budget_variance": (t[5] + t[6]) - disc_actual,
            "tp_value": tp, "net_wo_reg_value": wo, "net_value": net,
            "actual_pct": round(disc_actual / tp * 100, 1) if tp else None,
            "budget_pct": round((t[5] + t[6]) / t[0] * 100, 1) if t[0] else None,
        },
        "active_mio": pair(mio_act, mio_tgt),
        "active_spo": pair(spo_act, spo_tgt),
        "active_staff": pair(active_pos, float(head)),
        "active_shops": {"actual": shops, "total": transacting_shops,
                         "ach": round(shops / transacting_shops * 100, 1) if transacting_shops else None},
        "gross_profit_margin_pct": None,
        "active_field_staff": pair(hierarchy_active, hierarchy_total),
        "top_customer_performance_pct": max(
            (r["performance_pct"] for r in spo_sections["top_customers"] if r["performance_pct"] is not None),
            default=None),
        "returns": {"value": ret, "pct": round(ret / pos_gross * 100, 1) if pos_gross else None},
        # Flat, explicit individual KPI fields consumed by the KPI cards.
        "target_gap": t[target_index] - s[sales_index],
        "target_gap_status": "ahead" if s[sales_index] >= t[target_index] else "short",
        "productive_shops": shops,
        "avg_sales_per_productive_shop": s[sales_index] / shops if shops else 0,
        "spo_sections": spo_sections,
        "spo_metrics": {
            "target_gap": t[target_index] - s[sales_index],
            "avg_sales_per_shop": s[sales_index] / shops if shops else 0,
            "first_time_buying_shops": first_time,
            "previous": {"net_sales": prev[0], "units": prev[1], "shops": prev[2],
                          "returns_value": prev[3], "positive_gross": prev[4],
                          "avg_sales_per_shop": prev[5] / prev[2] if prev[2] else 0,
                          "return_pct": prev[3] / prev[4] * 100 if prev[4] else None}
        },
    }


@app.get("/api/kpis")
def kpis(
    designation: str = "HOD", region: str = "All", zone: str = "All", subzone: str = "All",
    territory: str = "All", employee: str = "All", team: str = "COMBINED",
    month: str = Query(..., description="e.g. Jul-2026"), fy: str = TARGET_FY,
    value_metric: str = "net_with_reg",
):
    generation = dashboard_data_generation()
    scope_positions = cached_authorized_positions(
        generation, designation, region, zone, subzone, territory, employee, team.upper(),
    )
    use_summaries = cached_summary_readiness(generation)
    key = (
        "kpis", "dashboard", designation, employee, region, zone, subzone,
        territory, team.upper(), month, fy, value_metric,
        authorized_scope_digest(scope_positions), use_summaries,
    )
    return cached_response(generation, key, lambda: _kpis_uncached(
        designation, region, zone, subzone, territory, employee, team, month, fy,
        value_metric, use_summaries=use_summaries, resolved_positions=scope_positions,
    ))


@app.get("/api/cache-stats")
def cache_stats():
    """Data-free cache effectiveness counters for operational monitoring."""
    return {
        "responses": response_cache.stats(),
        "authorized_scopes": scope_cache.stats(),
        "metadata": metadata_cache.stats(),
    }


@app.get("/api/db-pool-stats")
def db_pool_stats():
    """Data-free connection-pool health counters for operational monitoring."""
    return {
        **pool_metrics.snapshot(),
        "minimum": DB_POOL_MIN,
        "acquire_timeout_seconds": DB_POOL_ACQUIRE_TIMEOUT_SECONDS,
        "statement_timeout_ms": DB_STATEMENT_TIMEOUT_MS,
        "idle_transaction_timeout_ms": DB_IDLE_TRANSACTION_TIMEOUT_MS,
    }


def _ai_insights_legacy_uncached(
    designation: str = "HOD", region: str = "All", zone: str = "All", subzone: str = "All",
    territory: str = "All", employee: str = "All", month: str = Query(...), fy: str = TARGET_FY,
    entity: str = "sku", resolved_positions=None,
):
    """Return high/low SKU performers for the current dashboard scope."""
    check_designation(designation)
    if entity != "sku":
        return {"entity": entity, "high": [], "low": [], "counts": {"high": 0, "low": 0}, "available": False}
    try:
        d = dt.datetime.strptime(month, "%b-%Y")
    except ValueError:
        raise HTTPException(400, "month must look like Jul-2026")

    sales_month = f"{d.strftime('%B')},{d.strftime('%y')}"
    sfx = f"{d.strftime('%b').lower()}_{d.strftime('%y')}"
    cte, cte_params = scope_cte(
        designation, region, zone, subzone, territory, employee, target_suffix=sfx,
        resolved_positions=resolved_positions,
    )
    if fy != TARGET_FY:
        return {"entity": entity, "high": [], "low": [], "counts": {"high": 0, "low": 0}, "available": False}

    rows = query(f"""{cte}, sku_targets AS (
      SELECT product_no, SUM(COALESCE(tgt_net_w_reg_{sfx}, 0)) AS target_net_sales
      FROM target_data
      WHERE position_code_2026_27 IN (SELECT position_code FROM scope)
      GROUP BY product_no)
      SELECT s.product_no, MAX(s.prd_name), SUM({num('s.net_sale_value')}) AS actual_net_sales,
             COALESCE(MAX(t.target_net_sales), 0) AS target_net_sales
      FROM sales_data s
      LEFT JOIN sku_targets t ON t.product_no = s.product_no
      WHERE s.position_code IN (SELECT position_code FROM scope)
        AND s.reporting_month = %s AND s.fiscal_year = %s
      GROUP BY s.product_no
      HAVING COALESCE(MAX(t.target_net_sales), 0) > 0
      ORDER BY actual_net_sales DESC""", cte_params + [sales_month, fy])

    items = []
    for product_no, product_name, actual, target in rows:
        actual, target = float(actual or 0), float(target or 0)
        achievement = actual / target * 100 if target else None
        item = {"product_no": product_no, "name": product_name or "Unknown product",
                "actual": actual, "target": target, "achievement_pct": round(achievement, 1)}
        items.append(item)
    return {
        "entity": entity,
        "high": [x for x in items if x["achievement_pct"] >= 100],
        "low": [x for x in items if x["achievement_pct"] < 50],
        "counts": {
            "high": sum(x["achievement_pct"] >= 100 for x in items),
            "low": sum(x["achievement_pct"] < 50 for x in items),
        },
        "available": True,
    }


@app.get("/api/ai-insights-legacy")
def ai_insights_legacy(
    designation: str = "HOD", region: str = "All", zone: str = "All", subzone: str = "All",
    territory: str = "All", employee: str = "All", month: str = Query(...), fy: str = TARGET_FY,
    entity: str = "sku",
):
    if entity != "sku":
        return _ai_insights_legacy_uncached(
            designation, region, zone, subzone, territory, employee, month, fy, entity,
        )
    generation = dashboard_data_generation()
    scope_positions = cached_authorized_positions(
        generation, designation, region, zone, subzone, territory, employee, "COMBINED",
    )
    key = (
        "ai-insights-legacy", entity, designation, employee, region, zone, subzone,
        territory, "COMBINED", month, fy, authorized_scope_digest(scope_positions),
    )
    return cached_response(generation, key, lambda: _ai_insights_legacy_uncached(
        designation, region, zone, subzone, territory, employee, month, fy, entity,
        resolved_positions=scope_positions,
    ))


# ------------------------------------------------------ Ranked AI analysis
from services.ai_analysis import analyze, load_context


@app.get("/api/ai-insights")
def ai_insights(
    mode: str = "employee", designation: str = "HOD", region: str = "All", zone: str = "All",
    subzone: str = "All", territory: str = "All", employee: str = "All",
    month: str = Query(...), fy: str = TARGET_FY, team: str = "COMBINED",
    product: str = "All", product_group: str = "All",
    band: str = "all", offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
):
    if mode not in {"employee", "product"}:
        raise HTTPException(400, "mode must be employee or product")
    if band not in {"all", "high", "average", "low"}:
        raise HTTPException(400, "invalid band")
    team = team.upper()
    if team not in {"COMBINED", "FMCG", "PHARMA"}:
        raise HTTPException(400, "invalid team")
    try:
        date = dt.datetime.strptime(month, "%b-%Y")
    except ValueError:
        raise HTTPException(400, "month must look like Jul-2026")
    selected = dict(designation=designation, region=region, zone=zone, subzone=subzone,
                    territory=territory, employee=employee, month=month, fy=fy, team=team,
                    product=product, product_group=product_group, mode=mode)
    generation = dashboard_data_generation()
    scope_positions = cached_authorized_positions(
        generation, designation, region, zone, subzone, territory, employee, team,
    )
    use_summaries = (cached_summary_readiness(generation)
                     and scope_mode(designation) != "individual")
    key = (
        "ai-insights", mode, designation, employee, region, zone, subzone,
        territory, team, month, fy, product, product_group, band, offset, limit,
        authorized_scope_digest(scope_positions), use_summaries,
    )

    def compute():
        check_designation(designation)
        context = load_context(
            query, scope_cte, selected, date, TARGET_FY,
            resolved_positions=scope_positions,
            reporting_tree_resolver=resolve_reporting_tree,
            use_summaries=use_summaries,
        )
        result = analyze(context, limit=limit, offset=offset, band=band)
        product_names = {}
        for row in context["rows"]:
            if row["id"] and (row["id"] not in product_names or product_names[row["id"]] == row["id"]):
                product_names[row["id"]] = row["name"]
        result["product_options"] = sorted(product_names.items())
        result["product_group_options"] = sorted({
            row["group"] for row in context["rows"] if row.get("group")
        })
        return result

    return cached_response(generation, key, compute)


@app.get("/")
def index():
    return FileResponse(EXECUTIVE_DIR / "templates" / "index.html", media_type="text/html; charset=utf-8")


# Mount static assets for Executive Dashboard frontend
for folder in ("css", "js"):  # never expose .env
    app.mount(
        f"/{folder}",
        StaticFiles(directory=EXECUTIVE_DIR / "static" / folder),
        name=f"executive_{folder}",
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
