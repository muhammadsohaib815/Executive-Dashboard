"""
Executive Dashboard API
-----------------------
Serves the static dashboard and the JSON endpoints it needs.

Tables used (all joined through POSITION_CODE):
  * staff_master : hierarchy (report_to_position_code), designation, region/zone
  * sales_data   : actuals
  * target_data  : monthly targets (position_code_2026_27)
  * Inventory/stock ledger is intentionally not queried by this application.

Run:  python scripts/server.py     ->  http://localhost:8000
"""
import sys
import datetime as dt
import base64
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from copy import deepcopy
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from psycopg2 import sql as pgsql
from psycopg2.extras import execute_values
from psycopg2.pool import ThreadedConnectionPool
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for import_path in (ROOT, SCRIPT_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from scripts.performance_monitor import (
    DatabasePoolTimeout, EndpointTimingMiddleware, PoolMetrics,
    query_identifier, run_query,
)
from scripts.response_cache import TTLResponseCache
from scripts.services.sales_chat import (
    ChatPlanningError, UnsupportedQuestion, compile_query, format_answer, plan_question,
)

FRONTEND_DIR = ROOT / "frontend"
ASSETS_DIR = ROOT / "assets"
REQUEST_SCOPE_POSITION = contextvars.ContextVar("request_scope_position", default=None)


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


def chat_config(name: str) -> str:
    """Read a chat setting, tolerating optional quotes around .env values."""
    value = (os.getenv(name) or ENV.get(name) or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value

LOGGER = logging.getLogger("executive_dashboard.auth")
AUTH_COOKIE_NAME = "dashboard_session"
# Login roles are kept separate from the assigned staff position, but the
# administrator may use the same hierarchy labels for clearer account
# management and reporting (ASM, RSM, SPO, MIO/IO, etc.).
AUTH_ROLES = {"admin", "executive", "manager", "viewer"}
DESIGNATION_ROLES = {
    "ASM", "RSM", "DGM", "SPO", "MIO", "IO", "HOD", "EXEC",
    "PS", "SB", "ASMTE", "CM", "SPOWS", "TE",
}
AUTH_ROLE_VALUES = AUTH_ROLES | DESIGNATION_ROLES


def normalize_auth_role(value: str) -> str:
    raw = str(value or "").strip()
    if raw.lower() in AUTH_ROLES:
        return raw.lower()
    upper = raw.upper()
    if upper in DESIGNATION_ROLES:
        return upper
    return raw.lower()
AUTH_SESSION_TTL_SECONDS = 28800
AUTH_SECRET = ENV.get("AUTH_SECRET") or secrets.token_hex(32)
AUTH_COOKIE_SECURE = ENV.get("AUTH_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
PASSWORD_ITERATIONS = 260_000


def bounded_int_setting(name, default, minimum, maximum):
    try:
        value = int(ENV.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


AUTH_SESSION_TTL_SECONDS = bounded_int_setting("AUTH_SESSION_TTL_SECONDS", 28800, 900, 604800)


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


FISCAL_MONTHS = (7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 5, 6)


def fiscal_period_rows(month: str, mode: str = "MTD"):
    """Return reporting-month labels and target suffixes for MTD or YTD."""
    mode = (mode or "MTD").upper()
    if mode not in {"MTD", "YTD"}:
        raise HTTPException(400, "period must be MTD or YTD")
    try:
        selected = dt.datetime.strptime(month, "%b-%Y")
    except ValueError:
        raise HTTPException(400, "month must look like Jul-2026")
    if mode == "MTD":
        dates = [selected]
    else:
        first_year = selected.year if selected.month >= 7 else selected.year - 1
        cursor = dt.datetime(first_year, 7, 1)
        end = dt.datetime(selected.year, selected.month, 1)
        dates = []
        while cursor <= end:
            dates.append(cursor)
            cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return [
        {
            "date": value,
            "reporting_month": f"{value.strftime('%B')},{value.strftime('%y')}",
            "suffix": f"{value.strftime('%b').lower()}_{value.strftime('%y')}",
            "month": value.strftime("%b-%Y"),
        }
        for value in dates
    ]


def query(sql: str, params: list, query_id: str = None):
    query_id = query_id or query_identifier(sql)
    rows, _ = run_query(
        pool, sql, params, query_id, query_slots,
        DB_POOL_ACQUIRE_TIMEOUT_SECONDS, pool_metrics,
    )
    return rows


def execute_transaction(statement: str, params=None, query_id: str = "db.write"):
    """Execute a write with an explicit commit and always return the connection."""
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cursor:
            cursor.execute(statement, params or [])
            rows = cursor.fetchall() if cursor.description else []
        conn.commit()
        return rows
    except Exception:
        if conn is not None:
            conn.rollback()
        LOGGER.exception("database write failed: %s", query_id)
        raise
    finally:
        if conn is not None:
            pool.putconn(conn)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _token_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _token_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session(user: dict) -> str:
    payload = {
        "uid": int(user["id"]), "username": user["username"],
        "role": user["role"], "scope_position_code": user.get("scope_position_code"),
        "exp": int(time.time()) + AUTH_SESSION_TTL_SECONDS,
    }
    encoded = _token_part(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(AUTH_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_token_part(signature)}"


def decode_session(token: str | None):
    if not token or "." not in token:
        return None
    encoded, signature = token.split(".", 1)
    expected = hmac.new(AUTH_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    try:
        supplied = _token_bytes(signature)
        if not hmac.compare_digest(expected, supplied):
            return None
        payload = json.loads(_token_bytes(encoded).decode("utf-8"))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def session_from_request(request: Request):
    return decode_session(request.cookies.get(AUTH_COOKIE_NAME))


def current_user(request: Request):
    session = session_from_request(request)
    if not session:
        raise HTTPException(401, "Authentication required")
    rows = query(
        """SELECT id, username, full_name, role, is_active, created_at, last_login_at,
                  scope_position_code,
                  (SELECT NULLIF(TRIM(s.designation_name), '')
                     FROM public.staff_master s
                    WHERE TRIM(s.position_code) = TRIM(u.scope_position_code)
                    ORDER BY s.position_code LIMIT 1) AS designation_name
           FROM public.dashboard_users u WHERE id = %s LIMIT 1""",
        [session.get("uid")], "auth.current_user",
    )
    if not rows or not rows[0][4]:
        raise HTTPException(401, "Your account is inactive or no longer exists")
    row = rows[0]
    return {
        "id": row[0], "username": row[1], "full_name": row[2], "role": row[3],
        "is_active": row[4], "created_at": row[5].isoformat() if row[5] else None,
        "last_login_at": row[6].isoformat() if row[6] else None,
        "scope_position_code": row[7], "designation": row[8],
    }


def require_admin(request: Request):
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class SetupRequest(LoginRequest):
    full_name: str = Field(min_length=2, max_length=120)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="viewer", min_length=2, max_length=20)
    scope_position_code: str | None = Field(default=None, max_length=120)


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = Field(default=None, min_length=2, max_length=20)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    is_active: bool | None = None
    scope_position_code: str | None = Field(default=None, max_length=120)


class ActionPlanRequest(BaseModel):
    action_text: str = Field(min_length=1, max_length=4000)
    action_owner_position_code: str = Field(min_length=1, max_length=120)
    due_date: dt.date | None = None
    priority: str = Field(default="Medium", max_length=20)
    status: str = Field(default="Open", max_length=30)


class ActionPlanResponseRequest(BaseModel):
    response_text: str = Field(min_length=1, max_length=2000)


class ProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    profile_photo_data: str | None = Field(default=None, max_length=1_500_000)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class NotificationReadRequest(BaseModel):
    read: bool = True


class DataImportRequest(BaseModel):
    table: str = Field(min_length=1, max_length=80)
    rows: list[dict[str, object]] = Field(min_length=1, max_length=2000)


class SalesChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    filters: dict[str, str] = Field(default_factory=dict)


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
    key = (generation, "scope", REQUEST_SCOPE_POSITION.get(), designation, region, zone, subzone, territory, employee, team)
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
    request_anchor = REQUEST_SCOPE_POSITION.get()
    request_cte = ""
    if request_anchor:
        request_cte = (
            "WITH RECURSIVE request_positions(position_code) AS ("
            "SELECT position_code FROM public.staff_master WHERE position_code = %s "
            "UNION SELECT child.position_code FROM public.staff_master child "
            "JOIN request_positions parent ON TRIM(child.report_to_position_code) = TRIM(parent.position_code)), "
        )
        params.append(request_anchor)
        where.append("staff_master.position_code IN (SELECT position_code FROM request_positions)")
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
        if request_cte:
            sql = f"{request_cte}scope AS (SELECT position_code FROM staff_master WHERE {predicates})"
        else:
            sql = f"WITH scope AS (SELECT position_code FROM staff_master WHERE {predicates})"
    else:
        sql = request_cte + (
            "scope AS (" if request_cte else "WITH RECURSIVE scope AS ("
        ) + (
            f"SELECT position_code FROM staff_master WHERE {predicates} "
            "UNION SELECT m.position_code FROM staff_master m "
            "JOIN scope s ON TRIM(m.report_to_position_code) = TRIM(s.position_code) "
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
          JOIN scope parent ON TRIM(m.report_to_position_code) = TRIM(parent.position_code)
        )
        SELECT DISTINCT position_code FROM scope
        WHERE position_code IS NOT NULL ORDER BY position_code""",
        [position_code],
        "hierarchy.reporting_tree",
    )
    return list(dict.fromkeys(row[0] for row in rows if row and row[0] is not None))


def request_scope_positions():
    anchor = REQUEST_SCOPE_POSITION.get()
    return resolve_reporting_tree(anchor) if anchor else None


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
    scoped_positions = request_scope_positions()
    if scoped_positions is not None:
        conditions.append("position_code = ANY(%s)")
        params.append(scoped_positions)
    rows = query(
        "SELECT DISTINCT TRIM(designation_name) FROM staff_master WHERE "
        + " AND ".join(conditions) + " ORDER BY 1",
        params,
    )
    return ["ALL"] + [row[0] for row in rows]


def check_designation(d: str):
    if d in {"ALL", "All"}:
        return
    scoped_positions = request_scope_positions()
    sql = "SELECT 1 FROM staff_master WHERE designation_name = %s"
    params = [d]
    if scoped_positions is not None:
        sql += " AND position_code = ANY(%s)"
        params.append(scoped_positions)
    sql += " LIMIT 1"
    if not query(sql, params):
        raise HTTPException(400, f"Unknown designation '{d}'")


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(_app):
    yield
    pool.closeall()


app = FastAPI(title="Executive Dashboard API", lifespan=lifespan)
app.add_middleware(EndpointTimingMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


@app.middleware("http")
async def require_api_session(request: Request, call_next):
    path = request.url.path
    public = {
        "/api/auth/status", "/api/auth/login", "/api/auth/setup", "/api/auth/logout",
    }
    scope_token = None
    if path.startswith("/api/") and path not in public and request.method != "OPTIONS":
        session = session_from_request(request)
        if not session:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        users = query(
            "SELECT role, is_active, scope_position_code FROM public.dashboard_users WHERE id = %s LIMIT 1",
            [session.get("uid")], "auth.api_session_user",
        )
        if not users or not users[0][1]:
            return JSONResponse(status_code=401, content={"detail": "Your account is inactive or no longer exists"})
        if users[0][0] != "admin":
            if not users[0][2]:
                return JSONResponse(status_code=403, content={"detail": "Your account needs a staff hierarchy assignment. Contact an administrator."})
            scope_token = REQUEST_SCOPE_POSITION.set(users[0][2])
    try:
        return await call_next(request)
    finally:
        if scope_token is not None:
            REQUEST_SCOPE_POSITION.reset(scope_token)


@app.exception_handler(DatabasePoolTimeout)
async def database_pool_timeout_handler(_request, _exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Database capacity is temporarily busy; retry shortly."},
        headers={"Retry-After": "1"},
    )


def set_session_cookie(response, user):
    response.set_cookie(
        AUTH_COOKIE_NAME, create_session(user), max_age=AUTH_SESSION_TTL_SECONDS,
        httponly=True, secure=AUTH_COOKIE_SECURE, samesite="lax", path="/",
    )


def public_user(row):
    return {
        "id": row[0], "username": row[1], "full_name": row[2], "role": row[3],
        "is_active": row[4], "created_at": row[5].isoformat() if row[5] else None,
        "updated_at": row[6].isoformat() if row[6] else None,
        "last_login_at": row[7].isoformat() if row[7] else None,
        "scope_position_code": row[8] if len(row) > 8 else None,
    }


def validate_scope_position(scope_position_code, role):
    if role == "admin":
        return None
    code = (scope_position_code or "").strip()
    if not code:
        raise HTTPException(400, "Select a staff position to assign this user's hierarchy access")
    rows = query(
        "SELECT position_code FROM public.staff_master WHERE TRIM(position_code) = %s LIMIT 1",
        [code], "auth.validate_scope_position",
    )
    if not rows:
        raise HTTPException(400, "The selected staff position does not exist")
    return rows[0][0]


def scope_position_role(scope_position_code):
    """Return the immutable dashboard role represented by a staff position."""
    code = (scope_position_code or "").strip()
    if not code:
        raise HTTPException(400, "Select a staff position to assign this user's hierarchy access")
    rows = query(
        """SELECT UPPER(TRIM(designation_name))
             FROM public.staff_master
            WHERE TRIM(position_code) = %s
              AND NULLIF(TRIM(designation_name), '') IS NOT NULL
            ORDER BY position_code
            LIMIT 1""",
        [code], "auth.scope_position_role",
    )
    if not rows:
        raise HTTPException(400, "The selected staff position does not have a staff designation")
    designation = str(rows[0][0] or "").strip().upper()
    if designation not in DESIGNATION_ROLES:
        raise HTTPException(400, f"The selected staff position has unsupported designation '{designation}'")
    return designation


@app.get("/api/auth/status")
def auth_status(request: Request):
    rows = query("SELECT COUNT(*) FROM public.dashboard_users", [], "auth.user_count")
    setup_required = not rows or int(rows[0][0]) == 0
    user = None
    if not setup_required and session_from_request(request):
        try:
            user = current_user(request)
        except HTTPException:
            user = None
    return {"setup_required": setup_required, "authenticated": user is not None, "user": user}


@app.post("/api/auth/setup")
def auth_setup(payload: SetupRequest):
    rows = query("SELECT COUNT(*) FROM public.dashboard_users", [], "auth.user_count")
    if rows and int(rows[0][0]) > 0:
        raise HTTPException(409, "Initial administrator setup is already complete")
    username = payload.username.strip().lower()
    full_name = payload.full_name.strip()
    if not username or not full_name:
        raise HTTPException(400, "Username and full name are required")
    try:
        created = execute_transaction(
            """INSERT INTO public.dashboard_users
               (username, full_name, password_hash, role)
               VALUES (%s, %s, %s, 'admin')
               RETURNING id, username, full_name, role, is_active, created_at, updated_at, last_login_at""",
            [username, full_name, hash_password(payload.password)], "auth.setup_admin",
        )
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(409, "That username is already in use") from exc
        raise
    response = JSONResponse({"user": public_user(created[0])})
    set_session_cookie(response, {"id": created[0][0], "username": created[0][1], "role": created[0][3]})
    return response


@app.post("/api/auth/login")
def auth_login(payload: LoginRequest):
    username = payload.username.strip().lower()
    rows = query(
        """SELECT id, username, full_name, password_hash, role, is_active,
                  created_at, updated_at, last_login_at, scope_position_code
           FROM public.dashboard_users WHERE LOWER(username) = %s LIMIT 1""",
        [username], "auth.login",
    )
    if not rows or not rows[0][5] or not verify_password(payload.password, rows[0][3]):
        raise HTTPException(401, "Invalid username or password")
    row = rows[0]
    if row[4] != "admin" and not row[9]:
        raise HTTPException(403, "Your account is active but needs a staff hierarchy assignment. Ask an administrator to assign your position.")
    execute_transaction(
        "UPDATE public.dashboard_users SET last_login_at = NOW(), updated_at = NOW() WHERE id = %s",
        [row[0]], "auth.last_login",
    )
    user = {"id": row[0], "username": row[1], "full_name": row[2], "role": row[4], "scope_position_code": row[9]}
    response = JSONResponse({"user": {**user, "is_active": row[5]}})
    set_session_cookie(response, user)
    return response


@app.post("/api/auth/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return response


@app.get("/api/auth/me")
def auth_me(request: Request):
    return {"user": current_user(request)}


def profile_record(user_id: int):
    rows = query(
        """SELECT u.id, u.username, u.full_name, u.role, u.is_active,
                  u.created_at, u.last_login_at, u.scope_position_code,
                  u.profile_photo_data,
                  TRIM(s.designation_name), TRIM(s.employee_name),
                  TRIM(s.team_name), TRIM(s.dept_territory_code),
                  TRIM(s.region_name), TRIM(s.zone_name), TRIM(s.sub_zone)
             FROM public.dashboard_users u
             LEFT JOIN LATERAL (
               SELECT designation_name, employee_name, team_name,
                      dept_territory_code, region_name, zone_name, sub_zone
                 FROM public.staff_master
                WHERE TRIM(position_code) = TRIM(u.scope_position_code)
                ORDER BY position_code
                LIMIT 1
             ) s ON TRUE
            WHERE u.id = %s
            LIMIT 1""",
        [user_id], "auth.profile",
    )
    if not rows:
        raise HTTPException(404, "Profile not found")
    row = rows[0]
    return {
        "id": row[0], "username": row[1], "full_name": row[2], "role": row[3],
        "is_active": row[4], "created_at": row[5].isoformat() if row[5] else None,
        "last_login_at": row[6].isoformat() if row[6] else None,
        "scope_position_code": row[7], "profile_photo_data": row[8],
        "designation": row[9], "employee_name": row[10], "team": row[11],
        "territory": row[12], "region": row[13], "zone": row[14], "subzone": row[15],
    }


@app.get("/api/profile")
def get_profile(request: Request):
    return {"profile": profile_record(current_user(request)["id"])}


@app.patch("/api/profile")
def update_profile(payload: ProfileUpdateRequest, request: Request):
    user = current_user(request)
    full_name = payload.full_name.strip()
    if not full_name:
        raise HTTPException(400, "Full name is required")
    fields = ["full_name = %s", "updated_at = NOW()"]
    values = [full_name]
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    if "profile_photo_data" in fields_set:
        photo = payload.profile_photo_data
        if photo and not re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+", photo):
            raise HTTPException(400, "Profile photo must be a PNG, JPEG, or WebP image")
        fields.append("profile_photo_data = %s")
        values.append(photo)
    values.append(user["id"])
    execute_transaction(
        "UPDATE public.dashboard_users SET " + ", ".join(fields) + " WHERE id = %s",
        values, "auth.profile_update",
    )
    return {"profile": profile_record(user["id"])}


@app.post("/api/profile/password")
def change_profile_password(payload: PasswordChangeRequest, request: Request):
    user = current_user(request)
    rows = query("SELECT password_hash FROM public.dashboard_users WHERE id = %s", [user["id"]], "auth.profile_password")
    if not rows or not verify_password(payload.current_password, rows[0][0]):
        raise HTTPException(400, "Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(400, "New password must be different")
    execute_transaction(
        "UPDATE public.dashboard_users SET password_hash = %s, updated_at = NOW() WHERE id = %s",
        [hash_password(payload.new_password), user["id"]], "auth.profile_password_update",
    )
    return {"ok": True, "message": "Password changed successfully"}


@app.get("/api/admin/users")
def admin_users(request: Request):
    require_admin(request)
    rows = query(
        """SELECT id, username, full_name, role, is_active, created_at,
                  updated_at, last_login_at, scope_position_code
           FROM public.dashboard_users ORDER BY username""",
        [], "auth.admin_users",
    )
    return {"users": [public_user(row) for row in rows]}


@app.get("/api/admin/staff")
def admin_staff(request: Request):
    require_admin(request)
    rows = query(
        """SELECT position_code, employee_name, designation_name, team_name,
                  report_to_position_code, region_name, zone_name, sub_zone
           FROM public.staff_master WHERE NULLIF(TRIM(position_code), '') IS NOT NULL
           ORDER BY CASE UPPER(TRIM(designation_name)) WHEN 'RSM' THEN 1 WHEN 'ASM' THEN 2 WHEN 'MIO' THEN 3 WHEN 'SPO' THEN 4 ELSE 5 END,
                    employee_name, position_code""",
        [], "auth.admin_staff_hierarchy",
    )
    return {"staff": [
        {"position_code": row[0], "employee": row[1], "designation": row[2], "team": row[3],
         "reports_to": row[4], "region": row[5], "zone": row[6], "subzone": row[7]}
        for row in rows
    ]}


@app.post("/api/admin/users")
def admin_create_user(payload: UserCreateRequest, request: Request):
    require_admin(request)
    username = payload.username.strip().lower()
    full_name = payload.full_name.strip()
    role = normalize_auth_role(payload.role)
    if role not in AUTH_ROLE_VALUES:
        raise HTTPException(400, "role must be admin, executive, manager, viewer, or a staff designation such as ASM, RSM, DGM, SPO, or MIO")
    if not username or not full_name:
        raise HTTPException(400, "Username and full name are required")
    scope_position_code = validate_scope_position(payload.scope_position_code, role)
    if role != "admin":
        # A scoped account's role is always derived from its assigned staff
        # position. The submitted role is only a UI hint for new accounts.
        role = scope_position_role(scope_position_code)
    try:
        rows = execute_transaction(
            """INSERT INTO public.dashboard_users
               (username, full_name, password_hash, role, scope_position_code)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING id, username, full_name, role, is_active, created_at, updated_at, last_login_at, scope_position_code""",
            [username, full_name, hash_password(payload.password), role, scope_position_code], "auth.admin_create_user",
        )
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise HTTPException(409, "That username is already in use") from exc
        raise
    return {"user": public_user(rows[0])}


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, payload: UserUpdateRequest, request: Request):
    admin = require_admin(request)
    if admin["id"] == user_id and payload.is_active is False:
        raise HTTPException(400, "You cannot deactivate your own administrator account")
    existing_rows = query(
        "SELECT role, scope_position_code FROM public.dashboard_users WHERE id = %s",
        [user_id], "auth.admin_user_existing",
    )
    if not existing_rows:
        raise HTTPException(404, "User not found")
    existing_role, existing_scope = existing_rows[0]
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    fields, values = [], []
    if payload.full_name is not None:
        fields.append("full_name = %s"); values.append(payload.full_name.strip())
    if "scope_position_code" in fields_set or "role" in fields_set:
        requested_scope = payload.scope_position_code if "scope_position_code" in fields_set else existing_scope
        requested_role = normalize_auth_role(payload.role) if "role" in fields_set else existing_role
        if requested_role not in AUTH_ROLE_VALUES:
            raise HTTPException(400, "role must be admin, executive, manager, viewer, or a staff designation such as ASM, RSM, DGM, SPO, or MIO")
        if requested_role == "admin":
            if requested_scope:
                raise HTTPException(400, "Administrator accounts cannot be assigned a staff position")
            scope_position_code = None
            role = "admin"
        else:
            scope_position_code = validate_scope_position(requested_scope, requested_role)
            derived_role = scope_position_role(scope_position_code)
            if "role" in fields_set and requested_role != derived_role:
                raise HTTPException(400, f"Role is fixed by the assigned position ({derived_role})")
            role = derived_role
        fields.append("role = %s"); values.append(role)
        fields.append("scope_position_code = %s"); values.append(scope_position_code)
    if payload.password is not None:
        fields.append("password_hash = %s"); values.append(hash_password(payload.password))
    if payload.is_active is not None:
        fields.append("is_active = %s"); values.append(payload.is_active)
    if not fields:
        raise HTTPException(400, "No changes supplied")
    fields.append("updated_at = NOW()")
    values.append(user_id)
    rows = execute_transaction(
        "UPDATE public.dashboard_users SET " + ", ".join(fields) +
        " WHERE id = %s RETURNING id, username, full_name, role, is_active, created_at, updated_at, last_login_at, scope_position_code",
        values, "auth.admin_update_user",
    )
    return {"user": public_user(rows[0])}


@app.post("/api/admin/data-import")
def admin_data_import(payload: DataImportRequest, request: Request):
    require_admin(request)
    table = payload.table.strip().lower()
    allowed_tables = {
        "sales_data", "target_data", "staff_master", "call_data",
        "pharma_provider_calls", "fmcg_exception", "fmcg_cust_call",
    }
    if table not in allowed_tables:
        raise HTTPException(400, "The selected table is not approved for dashboard imports")
    columns = query(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = %s
           ORDER BY ordinal_position""",
        [table], "auth.import_columns",
    )
    allowed_columns = {row[0] for row in columns}
    if not allowed_columns:
        raise HTTPException(404, f"Table '{table}' was not found")
    requested = set().union(*(row.keys() for row in payload.rows))
    unknown = requested - allowed_columns
    if unknown:
        raise HTTPException(400, "Unknown columns: " + ", ".join(sorted(unknown)))
    if not requested:
        raise HTTPException(400, "Each row must contain at least one column")
    ordered_columns = sorted(requested)
    values = [[row.get(column) for column in ordered_columns] for row in payload.rows]
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cursor:
            statement = pgsql.SQL("INSERT INTO public.{} ({}) VALUES %s").format(
                pgsql.Identifier(table), pgsql.SQL(", ").join(pgsql.Identifier(column) for column in ordered_columns),
            )
            execute_values(cursor, statement.as_string(conn), values, page_size=500)
        conn.commit()
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        raise HTTPException(400, f"Import failed: {exc}") from exc
    finally:
        if conn is not None:
            pool.putconn(conn)
    return {"table": table, "rows_inserted": len(values), "columns": ordered_columns}


def can_choose_action_plan_owner(user: dict) -> bool:
    return str(user.get("role") or "").strip().lower() in {"admin", "exec", "executive"}


def reporting_manager_recipient(user: dict) -> dict:
    position_code = str(user.get("scope_position_code") or "").strip()
    if not position_code:
        raise HTTPException(403, "Your account needs an assigned staff position to send an action plan")
    rows = query(
        """SELECT TRIM(parent.position_code), TRIM(parent.employee_name),
                  TRIM(parent.designation_name)
           FROM public.staff_master child
           JOIN public.staff_master parent
             ON TRIM(parent.position_code) = TRIM(child.report_to_position_code)
           WHERE TRIM(child.position_code) = %s
             AND NULLIF(TRIM(parent.employee_name), '') IS NOT NULL
             AND NULLIF(TRIM(parent.designation_name), '') IS NOT NULL
           ORDER BY parent.position_code LIMIT 1""",
        [position_code], "actions.reporting_manager",
    )
    if not rows:
        raise HTTPException(403, "No reporting manager is assigned to your staff position")
    return {"position_code": rows[0][0], "employee_name": rows[0][1],
            "designation": rows[0][2]}


@app.get("/api/action-plan-recipient")
def action_plan_recipient(request: Request):
    user = current_user(request)
    if can_choose_action_plan_owner(user):
        raise HTTPException(400, "Use the action owner picker for this account")
    return {"recipient": reporting_manager_recipient(user)}


@app.get("/api/action-plan-recipients")
def action_plan_recipients(request: Request):
    if not can_choose_action_plan_owner(current_user(request)):
        raise HTTPException(403, "Only Admin and Executive accounts can choose an action owner")
    rows = query(
        """SELECT DISTINCT ON (TRIM(s.position_code))
                  TRIM(s.position_code), TRIM(s.employee_name), TRIM(s.designation_name), u.id
           FROM public.staff_master s
           LEFT JOIN LATERAL (
             SELECT account.id FROM public.dashboard_users account
              WHERE account.is_active = TRUE AND account.role <> 'admin'
                AND TRIM(account.scope_position_code) = TRIM(s.position_code)
              ORDER BY account.id LIMIT 1
           ) u ON TRUE
           WHERE NULLIF(TRIM(s.position_code), '') IS NOT NULL
             AND NULLIF(TRIM(s.employee_name), '') IS NOT NULL
             AND NULLIF(TRIM(s.designation_name), '') IS NOT NULL
           ORDER BY TRIM(s.position_code), TRIM(s.employee_name)""",
        [], "actions.recipients_staff",
    )
    return {"recipients": [
        {"position_code": row[0], "employee_name": row[1],
         "designation": row[2], "user_id": row[3]}
        for row in rows
    ], "recipient_label": "staff"}


@app.post("/api/action-plans")
def create_action_plan(payload: ActionPlanRequest, request: Request):
    user = current_user(request)
    if not payload.action_text.strip():
        raise HTTPException(400, "Corrective action is required")
    if payload.priority not in {"High", "Medium", "Low"}:
        raise HTTPException(400, "Priority must be High, Medium, or Low")
    if payload.status not in {"Open", "In Progress", "Complete"}:
        raise HTTPException(400, "Status must be Open, In Progress, or Complete")
    owner_code = payload.action_owner_position_code.strip()
    if not can_choose_action_plan_owner(user):
        manager = reporting_manager_recipient(user)
        if owner_code != manager["position_code"]:
            raise HTTPException(403, "Action plans from this account must go to its reporting manager")
    allowed = query(
        """SELECT TRIM(s.employee_name)
           FROM public.staff_master s
           WHERE TRIM(s.position_code) = %s
             AND NULLIF(TRIM(s.employee_name), '') IS NOT NULL
             AND NULLIF(TRIM(s.designation_name), '') IS NOT NULL
           ORDER BY s.employee_name LIMIT 1""",
        [owner_code], "actions.validate_owner",
    )
    if not allowed:
        raise HTTPException(400, "Selected action owner is not a valid staff position")
    owner_name = allowed[0][0]
    rows = execute_transaction(
        """WITH new_plan AS (
             INSERT INTO public.dashboard_action_plans
               (created_by_user_id, action_text, action_owner, action_owner_position_code,
                due_date, priority, status)
             VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
           ), queued AS (
             INSERT INTO public.dashboard_action_plan_positions (action_plan_id, position_code)
             SELECT new_plan.id, %s FROM new_plan
             RETURNING action_plan_id
           ), notified AS (
             INSERT INTO public.dashboard_action_plan_recipients (action_plan_id, recipient_user_id)
             SELECT queued.action_plan_id, account.id FROM queued
             JOIN public.dashboard_users account
               ON TRIM(account.scope_position_code) = %s
              AND account.is_active = TRUE AND account.role <> 'admin'
             ON CONFLICT (action_plan_id, recipient_user_id) DO NOTHING
             RETURNING recipient_user_id
           )
           SELECT new_plan.id, (SELECT COUNT(*) FROM notified) FROM new_plan""",
        [user["id"], payload.action_text.strip(), owner_name, owner_code, payload.due_date,
         payload.priority, payload.status, owner_code, owner_code], "actions.create_plan",
    )
    return {"ok": True, "action_plan_id": rows[0][0], "recipients": rows[0][1],
            "queued": rows[0][1] == 0}


def deliver_queued_action_plans(user):
    """Deliver position-addressed messages when a staff account becomes available."""
    position_code = str(user.get("scope_position_code") or "").strip()
    if not position_code or user.get("role") == "admin":
        return
    pending = query(
        """SELECT 1 FROM public.dashboard_action_plan_positions p
            WHERE p.position_code = %s
              AND NOT EXISTS (
                SELECT 1 FROM public.dashboard_action_plan_recipients r
                 WHERE r.action_plan_id = p.action_plan_id AND r.recipient_user_id = %s
              ) LIMIT 1""",
        [position_code, user["id"]], "actions.pending_delivery",
    )
    if not pending:
        return
    execute_transaction(
        """INSERT INTO public.dashboard_action_plan_recipients (action_plan_id, recipient_user_id)
           SELECT pending.action_plan_id, %s
             FROM public.dashboard_action_plan_positions pending
            WHERE pending.position_code = %s
           ON CONFLICT (action_plan_id, recipient_user_id) DO NOTHING
           RETURNING action_plan_id""",
        [user["id"], position_code], "actions.deliver_queued",
    )


@app.get("/api/notifications")
def get_notifications(request: Request):
    user = current_user(request)
    deliver_queued_action_plans(user)
    rows = query(
        """SELECT n.id, n.read_at, n.created_at, p.id, p.action_text, p.action_owner,
                  p.due_date, p.priority, p.status, creator.full_name,
                  latest.response_text, latest.responder_name, latest.response_created_at
           FROM public.dashboard_notifications n
           JOIN public.dashboard_action_plans p ON p.id = n.action_plan_id
           JOIN public.dashboard_users creator ON creator.id = p.created_by_user_id
           LEFT JOIN LATERAL (
             SELECT r.response_text, responder.full_name AS responder_name,
                    r.created_at AS response_created_at
               FROM public.dashboard_action_plan_responses r
               JOIN public.dashboard_users responder ON responder.id = r.sender_user_id
              WHERE r.action_plan_id = p.id
              ORDER BY r.created_at DESC, r.id DESC
              LIMIT 1
           ) latest ON TRUE
           WHERE n.recipient_user_id = %s
           ORDER BY n.created_at DESC, n.id DESC LIMIT 50""",
        [user["id"]], "notifications.inbox",
    )
    return {"unread_count": sum(1 for row in rows if row[1] is None), "notifications": [
        {"id": row[0], "read_at": row[1].isoformat() if row[1] else None,
         "created_at": row[2].isoformat() if row[2] else None, "action_plan_id": row[3],
         "action_text": row[4], "action_owner": row[5],
         "due_date": row[6].isoformat() if row[6] else None, "priority": row[7],
         "status": row[8], "sender": row[9],
         "latest_response": ({"text": row[10], "sender": row[11],
                              "created_at": row[12].isoformat() if row[12] else None}
                             if row[10] else None)}
        for row in rows
    ]}


@app.post("/api/action-plans/{action_plan_id}/responses")
def respond_to_action_plan(action_plan_id: int, payload: ActionPlanResponseRequest, request: Request):
    """Let an assigned employee acknowledge an action and notify its sender."""
    user = current_user(request)
    response_text = payload.response_text.strip()
    if not response_text:
        raise HTTPException(400, "Response message is required")
    assigned = query(
        """SELECT p.created_by_user_id
             FROM public.dashboard_action_plans p
             JOIN public.dashboard_action_plan_recipients r ON r.action_plan_id = p.id
            WHERE p.id = %s AND r.recipient_user_id = %s
            LIMIT 1""",
        [action_plan_id, user["id"]], "actions.response_authorization",
    )
    if not assigned:
        raise HTTPException(403, "This action plan is not assigned to your account")
    rows = execute_transaction(
        """WITH new_response AS (
               INSERT INTO public.dashboard_action_plan_responses
                    (action_plan_id, sender_user_id, response_text)
               VALUES (%s, %s, %s)
               RETURNING id
             ), notify_owner AS (
               INSERT INTO public.dashboard_notifications (recipient_user_id, action_plan_id)
               SELECT p.created_by_user_id, p.id
                 FROM public.dashboard_action_plans p
                WHERE p.id = %s
               ON CONFLICT (recipient_user_id, action_plan_id)
               DO UPDATE SET read_at = NULL, created_at = NOW()
               RETURNING action_plan_id
             )
             SELECT new_response.id FROM new_response CROSS JOIN notify_owner""",
        [action_plan_id, user["id"], response_text, action_plan_id],
        "actions.respond_to_plan",
    )
    return {"ok": True, "response_id": rows[0][0]}


@app.patch("/api/notifications/{notification_id}")
def set_notification_read(notification_id: int, payload: NotificationReadRequest, request: Request):
    user = current_user(request)
    rows = execute_transaction(
        """UPDATE public.dashboard_notifications SET read_at = CASE WHEN %s THEN NOW() ELSE NULL END
           WHERE id = %s AND recipient_user_id = %s RETURNING id""",
        [payload.read, notification_id, user["id"]], "notifications.mark_read",
    )
    if not rows:
        raise HTTPException(404, "Notification not found")
    return {"ok": True}


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
    scoped_positions = request_scope_positions()
    if scoped_positions is not None:
        base_where.append("position_code = ANY(%s)")
        base_params.append(scoped_positions)
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
    scoped_positions = request_scope_positions()
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
          AND (%s::text[] IS NULL OR position_code = ANY(%s))
        ORDER BY position_code""", [employee, scoped_positions, scoped_positions])
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


@app.get("/api/position-scope")
def position_scope(position_code: str = Query(..., min_length=1)):
    """Return the identity and geography for an assigned position code."""
    position_code = position_code.strip()
    scoped_positions = request_scope_positions()
    sql = f"""SELECT DISTINCT position_code, employee_name, designation_name,
          team_name, dept_territory_code, region_name, zone_name, sub_zone,
          department_name,
          CASE
            WHEN UPPER(TRIM(team_name)) LIKE '%%PHARM%%' THEN 'PHARMA'
            WHEN UPPER(TRIM(team_name)) LIKE '%%FMCG%%'
              OR UPPER(TRIM(team_name)) LIKE '%%FAST MOVING%%' THEN 'FMCG'
            ELSE 'COMBINED'
          END AS team_filter
        FROM staff_master
        WHERE TRIM(position_code) = %s
          AND (%s::text[] IS NULL OR position_code = ANY(%s))
        ORDER BY position_code"""
    rows = query(sql, [position_code, scoped_positions, scoped_positions], "filters.position_scope")
    if not rows:
        raise HTTPException(404, f"No staff-master record found for position '{position_code}'")
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
    scoped_positions = request_scope_positions()
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
          AND (%s::text[] IS NULL OR position_code = ANY(%s))
        ORDER BY position_code""", [territory, scoped_positions, scoped_positions], "filters.territory_scope")
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
    # Call-source extracts use `Jul-26`; retain `Jul,26` compatibility for
    # older imports while the source files are standardized.
    month_abbr = d.strftime('%b')
    month_aliases = [month_abbr]
    # Some imported Pharma files use "Sept" while the dashboard formatter
    # uses the standard three-letter "Sep" abbreviation.
    if month_abbr == "Sep":
        month_aliases.append("Sept")
    call_months = [
        token
        for alias in month_aliases
        for token in (f"{alias}-{d.strftime('%y')}", f"{alias},{d.strftime('%y')}")
    ]
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
      WHERE achievement_bottom_rank <= 25 OR achievement_top_rank <= 25
         OR discount_bottom_rank <= 25 OR discount_top_rank <= 25
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
    # Keep the top and bottom 25 available for the dashboard rankings.
    product_performance = list({
        r["group_on"]: r for r in ranked_products[:25] + ranked_products[-25:]
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
        r["group_on"]: r for r in ranked_discount_products[:25] + ranked_discount_products[-25:]
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
      FROM ranked_customers WHERE top_rank <= 25 OR bottom_rank <= 25
      ORDER BY net_sales DESC""", cte_params + [sales_month, fy])
    spo_sections["top_customers"] = [
        {"cust_name": r[0], "cust_number": r[1], "net_sales": float(r[2] or 0)}
        for r in customer_rows if r[3] <= 25
    ]
    spo_sections["bottom_customers"] = sorted([
        {"cust_name": r[0], "cust_number": r[1], "net_sales": float(r[2] or 0)}
        for r in customer_rows if r[4] <= 25
    ], key=lambda r: r["net_sales"])
    # A customer's percentage is its share of positive sales. Customer-level
    # targets do not exist, so this is never called target achievement.
    all_positive_sales = pos_sales
    all_positive_sales = pos_sales
    for customer in spo_sections["top_customers"] + spo_sections["bottom_customers"]:
        customer["performance_pct"] = round(max(0, customer["net_sales"]) / all_positive_sales * 100, 1) if all_positive_sales > 0 else None

    # Call data uses ff_id while dashboard filters use staff position codes.
    # The source ids are zero-padded versions of staff_master.hawk_emp_id, so
    # this join keeps every hierarchy, employee, region, and territory filter.
    call_source = "PHARMA" if team == "PHARMA" else "FMCG"
    call_data = {
        "available": True, "source_type": call_source, "manager_days": [], "shops": [],
        "outcomes": {"accepted": 0, "rejected": 0, "shop_closed": 0, "total": 0},
        "exceptions": {"total": 0, "attendance": 0, "leave": 0, "other": 0},
    }
    staff_call_join = (
        "LTRIM(TRIM(sm.hawk_emp_id), '0') = LTRIM(TRIM(c.ff_id), '0')"
    )
    if call_source == "PHARMA":
        manager_sql = f"""{cte}
          SELECT COALESCE(NULLIF(TRIM(c.manager), ''), 'Unassigned') AS manager,
                 COALESCE(NULLIF(TRIM(sm.employee_name), ''), NULLIF(TRIM(c.ff_name), ''), c.ff_id) AS employee,
                 sm.position_code,
                 COUNT(DISTINCT c.call_date) AS call_days,
                 SUM(COALESCE(c.no_of_calls, 1)) AS calls
          FROM public.pharma_provider_calls c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)
          GROUP BY c.manager, c.ff_name, c.ff_id, sm.employee_name, sm.position_code
          ORDER BY call_days DESC, calls DESC, employee
          LIMIT 10"""
        shops_sql = f"""{cte}
          SELECT COALESCE(NULLIF(TRIM(c.doctorname), ''), 'Unknown provider') AS provider_name,
                 SUM(COALESCE(c.no_of_calls, 1)) AS calls,
                 COUNT(DISTINCT c.call_date) AS call_days
          FROM public.pharma_provider_calls c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)
          GROUP BY c.doctorname
          ORDER BY calls DESC, call_days DESC, provider_name
          LIMIT 10"""
        outcomes_sql = f"""{cte}
          SELECT COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(REPLACE(TRIM(c.geometer_range), ' ', '')) = 'INRANGE'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(REPLACE(TRIM(c.geometer_range), ' ', '')) = 'OUTRANGE'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)), 0)
          FROM public.pharma_provider_calls c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)"""
        call_params = cte_params + [call_months]
        with ThreadPoolExecutor(max_workers=3) as executor:
            manager_future = submit_query(executor, "kpis.pharma_call_managers", manager_sql, call_params)
            shops_future = submit_query(executor, "kpis.pharma_call_providers", shops_sql, call_params)
            outcomes_future = submit_query(executor, "kpis.pharma_call_range", outcomes_sql, call_params)
            manager_call_rows = manager_future.result()
            shop_call_rows = shops_future.result()
            outcome_row = outcomes_future.result()[0]
        call_data["outcomes"] = {
            "accepted": int(outcome_row[0] or 0), "rejected": int(outcome_row[1] or 0),
            "shop_closed": 0, "total": int(outcome_row[2] or 0),
        }
    else:
        manager_sql = f"""{cte}, call_activity AS (
          SELECT c.ff_id, c.ff_name, c.manager, c.call_date, COALESCE(c.no_of_calls, 1) AS calls
          FROM public.fmcg_cust_call c WHERE c.month = ANY(%s)
          UNION ALL
          SELECT c.ff_id, c.ff_name, c.manager, c.call_date, COALESCE(c.no_of_calls, 1) AS calls
          FROM public.fmcg_exception c WHERE c.month = ANY(%s)
        )
          SELECT COALESCE(NULLIF(TRIM(c.manager), ''), 'Unassigned') AS manager,
                 COALESCE(NULLIF(TRIM(sm.employee_name), ''), NULLIF(TRIM(c.ff_name), ''), c.ff_id) AS employee,
                 sm.position_code,
                 COUNT(DISTINCT c.call_date) AS call_days,
                 SUM(c.calls) AS calls
          FROM call_activity c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
          GROUP BY c.manager, c.ff_name, c.ff_id, sm.employee_name, sm.position_code
          ORDER BY call_days DESC, calls DESC, employee
          LIMIT 10"""
        shops_sql = f"""{cte}
          SELECT COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Unknown shop') AS customer_name,
                 SUM(COALESCE(c.no_of_calls, 1)) AS calls,
                 COUNT(DISTINCT c.call_date) AS call_days
          FROM public.fmcg_cust_call c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)
          GROUP BY c.customer_name
          ORDER BY calls DESC, call_days DESC, customer_name
          LIMIT 10"""
        outcomes_sql = f"""{cte}
          SELECT COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(TRIM(c.\"order\")) = 'ACCEPTED'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(TRIM(c.\"order\")) = 'REJECTED'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(REPLACE(TRIM(c.\"order\"), ' ', '')) = 'SHOPCLOSED'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)), 0)
          FROM public.fmcg_cust_call c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)"""
        exceptions_sql = f"""{cte}
          SELECT COALESCE(SUM(COALESCE(c.no_of_calls, 1)), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(TRIM(c.call_nature)) = 'ATTENDANCE'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(TRIM(c.call_nature)) = 'LEAVE'), 0),
                 COALESCE(SUM(COALESCE(c.no_of_calls, 1)) FILTER (
                   WHERE UPPER(TRIM(c.call_nature)) NOT IN ('ATTENDANCE', 'LEAVE')), 0)
          FROM public.fmcg_exception c
          JOIN public.staff_master sm ON {staff_call_join}
          WHERE sm.position_code IN (SELECT position_code FROM scope)
            AND c.month = ANY(%s)"""
        call_params = cte_params + [call_months]
        with ThreadPoolExecutor(max_workers=4) as executor:
            manager_future = submit_query(
                executor, "kpis.fmcg_call_managers", manager_sql,
                cte_params + [call_months, call_months],
            )
            shops_future = submit_query(executor, "kpis.fmcg_call_shops", shops_sql, call_params)
            outcomes_future = submit_query(executor, "kpis.fmcg_call_outcomes", outcomes_sql, call_params)
            exceptions_future = submit_query(executor, "kpis.fmcg_call_exceptions", exceptions_sql, call_params)
            manager_call_rows = manager_future.result()
            shop_call_rows = shops_future.result()
            outcome_row = outcomes_future.result()[0]
            exception_row = exceptions_future.result()[0]
        call_data["outcomes"] = {
            "accepted": int(outcome_row[0] or 0), "rejected": int(outcome_row[1] or 0),
            "shop_closed": int(outcome_row[2] or 0), "total": int(outcome_row[3] or 0),
        }
        call_data["exceptions"] = {
            "total": int(exception_row[0] or 0), "attendance": int(exception_row[1] or 0),
            "leave": int(exception_row[2] or 0), "other": int(exception_row[3] or 0),
        }

    call_data["manager_days"] = [
        {"manager": r[0], "employee": r[1], "position_code": r[2],
         "call_days": int(r[3] or 0), "calls": int(r[4] or 0)}
        for r in manager_call_rows
    ]
    call_data["shops"] = [
        {"customer_name": r[0], "calls": int(r[1] or 0), "call_days": int(r[2] or 0)}
        for r in shop_call_rows
    ]

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
        WHERE role_bottom_rank <= 25 OR role_top_rank <= 25
           OR all_bottom_rank <= 25 OR all_top_rank <= 25
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


def _ytd_kpis_uncached(
    designation, region, zone, subzone, territory, employee, team, month, fy,
    value_metric, use_summaries, resolved_positions,
):
    """Build YTD KPIs from month-level calculations and exact distinct counts."""
    periods = fiscal_period_rows(month, "YTD")
    monthly = [
        _kpis_uncached(
            designation, region, zone, subzone, territory, employee, team,
            item["month"], fy, value_metric,
            use_summaries=use_summaries, resolved_positions=resolved_positions,
        )
        for item in periods
    ]
    if not monthly:
        return _kpis_uncached(
            designation, region, zone, subzone, territory, employee, team,
            month, fy, value_metric, use_summaries=use_summaries,
            resolved_positions=resolved_positions,
        )

    result = deepcopy(monthly[-1])
    additive_pairs = ("gross_tp", "net_sales", "net_sales_value", "units", "net_wo_reg", "cyp")
    for field in additive_pairs:
        result[field] = {
            "actual": sum(float(item[field].get("actual") or 0) for item in monthly),
            "target": sum(float(item[field].get("target") or 0) for item in monthly),
        }
        target = result[field]["target"]
        result[field]["ach"] = round(result[field]["actual"] / target * 100, 1) if target else None

    selected_field = {
        "tp": "gross_tp", "net_with_reg": "net_sales_value",
        "units": "units", "cyp": "cyp",
    }.get(value_metric, "net_sales_value")
    current_value = result[selected_field]["actual"]
    previous_value = sum(
        float(item[selected_field].get("actual") or 0) for item in monthly[:-1]
    )
    result["golm"] = round((current_value - previous_value) / abs(previous_value) * 100, 1) if previous_value else None
    result["golm_previous_value"] = previous_value

    period_months = [item["reporting_month"] for item in periods]
    latest_suffix = periods[-1]["suffix"]
    scope_cte_sql, scope_params = scope_cte(
        designation, region, zone, subzone, territory, employee, team,
        latest_suffix, resolved_positions=resolved_positions,
    )
    summary_team = team_predicate("s.team", team)
    customer_source = "public.sales_monthly_customer_summary" if use_summaries else "sales_data"
    position_source = "public.sales_monthly_position_summary" if use_summaries else "sales_data"
    customer_positive = "s.has_positive_sale" if use_summaries else f"{num('s.net_sale_value')} > 0"
    position_positive = "s.positive_sale_rows > 0" if use_summaries else f"{num('s.net_sale_value')} > 0"

    customer_counts = query(
        f"""{scope_cte_sql}
          SELECT COUNT(DISTINCT s.cust_number) FILTER (WHERE {customer_positive}),
                 COUNT(DISTINCT s.cust_number)
          FROM {customer_source} s
          WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month = ANY(%s) AND s.fiscal_year = %s
            AND {summary_team}""",
        scope_params + [period_months, fy], "kpis.ytd.customers",
    )[0]
    position_counts = query(
        f"""{scope_cte_sql}
          SELECT COUNT(DISTINCT s.position_code) FILTER (WHERE {position_positive}),
                 COUNT(DISTINCT CASE WHEN m.designation_name = 'MIO' AND {position_positive} THEN s.position_code END),
                 COUNT(DISTINCT CASE WHEN m.designation_name = 'SPO' AND {position_positive} THEN s.position_code END)
          FROM {position_source} s
          JOIN staff_master m ON m.position_code = s.position_code
          WHERE s.position_code IN (SELECT position_code FROM scope)
            AND s.reporting_month = ANY(%s) AND s.fiscal_year = %s
            AND {summary_team}""",
        scope_params + [period_months, fy], "kpis.ytd.positions",
    )[0]

    active_shops, transacting_shops = (int(customer_counts[0] or 0), int(customer_counts[1] or 0))
    active_staff, active_mio, active_spo = (int(position_counts[0] or 0), int(position_counts[1] or 0), int(position_counts[2] or 0))
    result["active_shops"] = {
        "actual": active_shops, "total": transacting_shops,
        "ach": round(active_shops / transacting_shops * 100, 1) if transacting_shops else None,
    }
    result["productive_shops"] = active_shops
    result["avg_sales_per_productive_shop"] = current_value / active_shops if active_shops else 0
    result["active_staff"] = {
        "actual": active_staff,
        "total": result.get("active_staff", {}).get("total", active_staff),
        "ach": round(active_staff / result.get("active_staff", {}).get("total", active_staff) * 100, 1)
        if result.get("active_staff", {}).get("total", active_staff) else None,
    }
    for field, actual in (("active_mio", active_mio), ("active_spo", active_spo)):
        result[field]["actual"] = actual
        target = result[field].get("target") or result[field].get("total") or 0
        result[field]["ach"] = round(actual / target * 100, 1) if target else None

    result["returns"] = {
        "value": sum(float(item["returns"].get("value") or 0) for item in monthly),
        "pct": None,
    }
    positive_gross = sum(float(item["discount"].get("tp_value") or 0) for item in monthly)
    result["returns"]["pct"] = round(result["returns"]["value"] / positive_gross * 100, 1) if positive_gross else None

    discount = result["discount"]
    for field in ("actual", "budget", "bonus_discount", "regular_discount", "budget_additional_discount", "budget_regular_discount", "budget_variance", "tp_value", "net_wo_reg_value", "net_value"):
        discount[field] = sum(float(item["discount"].get(field) or 0) for item in monthly)
    discount["actual_pct"] = round(discount["actual"] / discount["tp_value"] * 100, 1) if discount["tp_value"] else None
    discount["budget_pct"] = round(discount["budget"] / result["gross_tp"]["target"] * 100, 1) if result["gross_tp"]["target"] else None

    result["first_time_buying_shops"] = sum(
        float(item.get("spo_metrics", {}).get("first_time_buying_shops") or 0) for item in monthly
    )
    result.setdefault("spo_metrics", {})["first_time_buying_shops"] = result["first_time_buying_shops"]
    result["spo_metrics"]["target_gap"] = result["target_gap"] if "target_gap" in result else result[selected_field]["target"] - result[selected_field]["actual"]
    result["spo_metrics"]["avg_sales_per_shop"] = result["avg_sales_per_productive_shop"]
    result["target_gap"] = result[selected_field]["target"] - result[selected_field]["actual"]
    result["target_gap_status"] = "ahead" if result[selected_field]["actual"] >= result[selected_field]["target"] else "short"
    result["meta"] = dict(result.get("meta", {}), period="YTD", period_months=period_months, period_end=month)
    return result


@app.get("/api/kpis")
def kpis(
    designation: str = "HOD", region: str = "All", zone: str = "All", subzone: str = "All",
    territory: str = "All", employee: str = "All", team: str = "COMBINED",
    month: str = Query(..., description="e.g. Jul-2026"), fy: str = TARGET_FY,
    value_metric: str = "net_with_reg", period: str = "MTD",
):
    generation = dashboard_data_generation()
    scope_positions = cached_authorized_positions(
        generation, designation, region, zone, subzone, territory, employee, team.upper(),
    )
    use_summaries = cached_summary_readiness(generation)
    period = period.upper()
    if period not in {"MTD", "YTD"}:
        raise HTTPException(400, "period must be MTD or YTD")
    key = (
        "kpis", "dashboard", designation, employee, region, zone, subzone,
        territory, team.upper(), month, fy, value_metric, period,
        authorized_scope_digest(scope_positions), use_summaries,
    )
    def compute():
        if period == "YTD":
            return _ytd_kpis_uncached(
                designation, region, zone, subzone, territory, employee, team,
                month, fy, value_metric, use_summaries, scope_positions,
            )
        result = _kpis_uncached(
            designation, region, zone, subzone, territory, employee, team,
            month, fy, value_metric, use_summaries=use_summaries,
            resolved_positions=scope_positions,
        )
        result.setdefault("meta", {})["period"] = "MTD"
        result["meta"]["period_end"] = month
        return result

    return cached_response(generation, key, compute)


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
from scripts.services.ai_analysis import analyze, load_context


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
    # A scoped account may not use the national ALL lens through a crafted
    # request.  Pick the most useful accessible level for that account (field
    # users see themselves; managers see their direct reporting level).  The
    # selected designation is still checked below and the hierarchy CTE keeps
    # every result inside the assigned reporting tree.
    if REQUEST_SCOPE_POSITION.get() and designation in {"ALL", "All"}:
        available = [str(value).upper() for value in designation_options(team) if str(value).upper() != "ALL"]
        own_rows = query(
            "SELECT DISTINCT UPPER(TRIM(designation_name)) FROM staff_master WHERE position_code = %s LIMIT 1",
            [REQUEST_SCOPE_POSITION.get()], "ai.scope_designation",
        )
        own = own_rows[0][0] if own_rows and own_rows[0][0] else ""
        preferred = {
            "EXEC": ("RSM", "ASM", "SPO", "MIO"), "HOD": ("RSM", "ASM", "SPO", "MIO"),
            "DGM": ("RSM", "ASM", "SPO", "MIO"), "RSM": ("ASM", "SPO", "MIO"),
            "ASM": ("SPO", "MIO", "PS", "SB", "ASMTE", "CM", "SPOWS", "TE"),
        }
        designation = own if own in INDIVIDUAL and own in available else next(
            (value for value in preferred.get(own, ()) if value in available),
            own if own in available else (available[0] if available else "ALL"),
        )
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


@app.post("/api/sales-chat")
def sales_chat(payload: SalesChatRequest):
    """Plan and run a scoped, read-only sales query for the signed-in user."""
    allowed = ("designation", "region", "zone", "subzone", "territory", "employee",
               "team", "month", "fy", "period")
    filters = {key: str(payload.filters.get(key) or "").strip() for key in allowed}
    if any(len(value) > 120 for value in filters.values()):
        raise HTTPException(400, "A filter value is too long")
    filters["designation"] = filters["designation"] or "HOD"
    for key in ("region", "zone", "subzone", "territory", "employee"):
        filters[key] = filters[key] or "All"
    filters["team"] = (filters["team"] or "COMBINED").upper()
    filters["fy"] = filters["fy"] or TARGET_FY
    filters["period"] = (filters["period"] or "MTD").upper()
    if filters["team"] not in {"COMBINED", "FMCG", "PHARMA"}:
        raise HTTPException(400, "invalid team")
    if filters["period"] not in {"MTD", "YTD"}:
        raise HTTPException(400, "period must be MTD or YTD")
    try:
        parsed_month = dt.datetime.strptime(filters["month"], "%b-%Y")
        if parsed_month.strftime("%b-%Y") != filters["month"]:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "month must look like Jul-2026")

    api_key = chat_config("GEMINI_API_KEY")
    model = chat_config("GEMINI_MODEL") or "gemini-3.6-flash"
    try:
        plan = plan_question(payload.question, filters, api_key, model)
        generation = dashboard_data_generation()
        positions = cached_authorized_positions(
            generation, filters["designation"], filters["region"], filters["zone"],
            filters["subzone"], filters["territory"], filters["employee"], filters["team"],
        )
        if not positions:
            return {"answer": "No sales positions are available for the selected scope.",
                    "source": "Sales SQL", "scope": filters["month"]}
        sql, params, months, _ = compile_query(plan, filters, positions, team_predicate)
        rows = query(sql, params, "sales_chat.text_sql")
        answer, scope = format_answer(plan, filters, rows, months)
        return {"answer": answer, "source": "Sales SQL", "scope": scope,
                "sql": sql, "query": {"measure": plan["measure"], "comparison": plan["comparison"],
                "dimension": plan["dimension"], "months": months,
                "authorized_positions": len(positions), "row_count": len(rows)}}
    except UnsupportedQuestion as exc:
        return {"answer": str(exc), "source": "Sales SQL", "scope": filters["month"]}
    except ChatPlanningError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/")
def index(request: Request):
    page = "index.html" if session_from_request(request) else "login.html"
    return FileResponse(FRONTEND_DIR / "html" / page, media_type="text/html; charset=utf-8")


@app.get("/dashboard")
def dashboard_page(request: Request):
    if not session_from_request(request):
        return RedirectResponse(url="/")
    return FileResponse(FRONTEND_DIR / "html" / "index.html", media_type="text/html; charset=utf-8")


@app.get("/admin")
def admin_page(request: Request):
    try:
        user = current_user(request)
    except HTTPException:
        return RedirectResponse(url="/")
    if user.get("role") != "admin":
        return HTMLResponse(
            "<h1>Administrator access required</h1><p>Your account cannot open this page.</p>",
            status_code=403,
        )
    return FileResponse(FRONTEND_DIR / "html" / "admin.html", media_type="text/html; charset=utf-8")


# Mount frontend assets from dedicated folders; never expose .env.
for folder in ("css", "js"):
    app.mount(
        f"/{folder}",
        StaticFiles(directory=FRONTEND_DIR / folder),
        name=f"frontend_{folder}",
    )
app.mount("/images", StaticFiles(directory=ASSETS_DIR / "images"), name="images")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
