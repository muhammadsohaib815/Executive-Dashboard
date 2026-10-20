"""Atomically rebuild selected monthly sales summaries from source transactions."""

import argparse
import datetime as dt
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    ("sales_monthly_position_summary",
     ("reporting_month", "fiscal_year", "team", "position_code"), {}),
    ("sales_monthly_product_summary",
     ("reporting_month", "fiscal_year", "team", "product_no", "group_on"),
     {"prd_name": "MAX(prd_name)"}),
    ("sales_monthly_customer_summary",
     ("reporting_month", "fiscal_year", "team", "position_code", "product_no",
      "group_on", "cust_number", "cust_name"),
     {"has_positive_sale": "BOOL_OR(COALESCE(net_sale_value, 0) > 0)"}),
    ("sales_monthly_position_product_summary",
     ("reporting_month", "fiscal_year", "team", "position_code", "product_no", "group_on"),
     {"prd_name": "MAX(prd_name)"}),
)

# SUM(raw) retains SQL NULL behavior. KPI callers may COALESCE the final sum;
# AI queries can still distinguish an all-NULL group using the stored counts.
METRICS = {
    "transaction_count": "COUNT(*)",
    "gross_tp_value": "SUM(tp_sale_value)",
    "net_sale_value": "SUM(net_sale_value)",
    "net_wo_reg_disc_value": "SUM(net_wo_reg_disc_value)",
    "units": "SUM(e_qty)",
    "net_qty": "SUM(net_qty)",
    "cyp": "SUM(cyp)",
    "discounts": "SUM(discounts)",
    "bonus_discount": "SUM(bonus_discount)",
    "mnp_commission": "SUM(mnp_commission)",
    "net_value": "SUM(net_value)",
    "positive_net_sale_value": "SUM(net_sale_value) FILTER (WHERE COALESCE(net_sale_value, 0) > 0)",
    "positive_tp_sale_value": "SUM(tp_sale_value) FILTER (WHERE COALESCE(tp_sale_value, 0) > 0)",
    "negative_net_sale_abs": "SUM(ABS(net_sale_value)) FILTER (WHERE COALESCE(net_sale_value, 0) < 0)",
    "return_impact_value": (
        "SUM(CASE WHEN net_sale_value < 0 OR net_qty < 0 OR net_value < 0 "
        "THEN ABS(net_sale_value) ELSE 0 END)"
    ),
    "net_sale_value_rows": "COUNT(net_sale_value)",
    "net_qty_rows": "COUNT(net_qty)",
    "positive_sale_rows": "COUNT(*) FILTER (WHERE COALESCE(net_sale_value, 0) > 0)",
    "active_customer_count": (
        "COUNT(DISTINCT cust_number) FILTER (WHERE COALESCE(net_sale_value, 0) > 0)"
    ),
    "transacting_customer_count": "COUNT(DISTINCT cust_number)",
}

SOURCE_COLUMNS = (
    "reporting_month", "fiscal_year", "team", "position_code", "product_no",
    "group_on", "cust_number", "cust_name", "prd_name", "tp_sale_value",
    "net_sale_value", "net_wo_reg_disc_value", "e_qty", "net_qty", "cyp",
    "discounts", "bonus_discount", "mnp_commission", "net_value",
)


def load_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def insert_sql(table, dimensions, extras, schema="public"):
    """Build an INSERT from fixed, reviewed table and column specifications."""
    columns = (*dimensions, *extras, *METRICS)
    selections = (*dimensions, *extras.values(), *METRICS.values())
    return (
        f"INSERT INTO {schema}.{table} ({', '.join(columns)}) "
        f"SELECT {', '.join(selections)} FROM pg_temp.sales_summary_source "
        f"GROUP BY {', '.join(dimensions)}"
    )


def periods_to_refresh(cursor, mode, month=None, fy=None, schema="public", source="public.sales_data"):
    if mode == "period":
        return [(month, fy)]
    if mode == "dirty":
        cursor.execute(
            f"SELECT reporting_month, fiscal_year FROM {schema}.sales_monthly_summary_dirty_period "
            "ORDER BY fiscal_year, reporting_month"
        )
    else:
        cursor.execute(
            f"""SELECT reporting_month, fiscal_year FROM {source}
                WHERE reporting_month IS NOT NULL AND fiscal_year IS NOT NULL
                UNION
                SELECT reporting_month, fiscal_year
                FROM {schema}.sales_monthly_summary_refresh_state
                UNION
                SELECT reporting_month, fiscal_year
                FROM {schema}.sales_monthly_summary_dirty_period
                ORDER BY fiscal_year, reporting_month"""
        )
    return cursor.fetchall()


def refresh_periods(cursor, periods, schema="public", source="public.sales_data"):
    """Rebuild every selected period in the caller's single repeatable-read transaction."""
    if not periods:
        return {}
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('sales_monthly_summary_refresh'))")
    cursor.execute("SET LOCAL lock_timeout = '10s'")
    cursor.execute("SET LOCAL statement_timeout = '30min'")
    cursor.execute(
        "CREATE TEMP TABLE sales_summary_periods ("
        "reporting_month text NOT NULL, fiscal_year text NOT NULL, "
        "PRIMARY KEY (reporting_month, fiscal_year)) ON COMMIT DROP"
    )
    execute_values(
        cursor,
        "INSERT INTO pg_temp.sales_summary_periods (reporting_month, fiscal_year) VALUES %s",
        periods,
    )
    # Lock existing markers before the source snapshot is materialized. A
    # concurrent correction waits, then writes a fresh marker after commit.
    cursor.execute(
        f"""SELECT d.reporting_month, d.fiscal_year
            FROM {schema}.sales_monthly_summary_dirty_period d
            JOIN pg_temp.sales_summary_periods p USING (reporting_month, fiscal_year)
            FOR UPDATE OF d"""
    )
    cursor.fetchall()
    cursor.execute(
        f"""CREATE TEMP TABLE sales_summary_source ON COMMIT DROP AS
            SELECT {', '.join('s.' + column for column in SOURCE_COLUMNS)}
            FROM {source} s
            JOIN pg_temp.sales_summary_periods p
              ON p.reporting_month = s.reporting_month
             AND p.fiscal_year = s.fiscal_year"""
    )
    for table, dimensions, extras in TABLES:
        cursor.execute(
            f"DELETE FROM {schema}.{table} AS summary "
            "USING pg_temp.sales_summary_periods p "
            "WHERE summary.reporting_month = p.reporting_month "
            "AND summary.fiscal_year = p.fiscal_year"
        )
        cursor.execute(insert_sql(table, dimensions, extras, schema))
    cursor.execute(
        f"""INSERT INTO {schema}.sales_monthly_summary_refresh_state
            (reporting_month, fiscal_year, source_rows, refreshed_at)
            SELECT p.reporting_month, p.fiscal_year, COUNT(s.reporting_month), clock_timestamp()
            FROM pg_temp.sales_summary_periods p
            LEFT JOIN pg_temp.sales_summary_source s USING (reporting_month, fiscal_year)
            GROUP BY p.reporting_month, p.fiscal_year
            ON CONFLICT (reporting_month, fiscal_year) DO UPDATE
            SET source_rows = EXCLUDED.source_rows,
                refreshed_at = EXCLUDED.refreshed_at"""
    )
    cursor.execute(
        f"DELETE FROM {schema}.sales_monthly_summary_dirty_period d "
        "USING pg_temp.sales_summary_periods p "
        "WHERE d.reporting_month = p.reporting_month "
        "AND d.fiscal_year = p.fiscal_year"
    )
    cursor.execute(
        f"""SELECT reporting_month, fiscal_year, source_rows
            FROM {schema}.sales_monthly_summary_refresh_state s
            JOIN pg_temp.sales_summary_periods p USING (reporting_month, fiscal_year)
            ORDER BY fiscal_year, reporting_month"""
    )
    return {(month, fy): count for month, fy, count in cursor.fetchall()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="Backfill all source and prior summary periods")
    mode.add_argument("--dirty", action="store_true", help="Refresh all changed periods")
    mode.add_argument("--month", help="A single reporting month, e.g. August,26")
    parser.add_argument("--fy", help="Fiscal year when --month is used, e.g. 2026-27")
    parser.add_argument("--expect-db", required=True, help="Exact destination database name")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--apply", action="store_true", help="Commit the refresh; default is a read-only plan")
    args = parser.parse_args()
    if bool(args.month) != bool(args.fy):
        parser.error("--month and --fy must be supplied together")
    if args.month:
        try:
            dt.datetime.strptime(args.month, "%B,%y")
        except ValueError:
            parser.error("--month must look like August,26")
    env = load_env(args.env_file)
    conn = psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10,
    )
    try:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=not args.apply)
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != args.expect_db:
                raise RuntimeError("Database name mismatch; no refresh performed")
            selected = periods_to_refresh(
                cursor, "all" if args.all else "dirty" if args.dirty else "period",
                args.month, args.fy,
            )
            print(f"Periods selected: {len(selected)}")
            for month, fy in selected:
                print(f"  {month} / {fy}")
            if args.apply:
                counts = refresh_periods(cursor, selected)
                if selected:
                    if __package__:
                        from .validate_sales_monthly_summaries import validate
                    else:
                        from validate_sales_monthly_summaries import validate

                    report = validate(cursor, selected)
                    if (any(report["grain_mismatches"].values())
                            or report["kpi_mismatches"]
                            or any(report["distinct_mismatches"].values())
                            or report["source_row_mismatches"]):
                        raise RuntimeError("Summary validation failed; refresh rolled back")
                conn.commit()
                for (month, fy), count in counts.items():
                    print(f"Refreshed {month} / {fy}: {count} source rows")
            else:
                conn.rollback()
                print("Plan only; no summary tables changed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
