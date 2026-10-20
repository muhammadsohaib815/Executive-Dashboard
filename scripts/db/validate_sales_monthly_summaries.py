"""Compare installed monthly summary rows and KPI rollups with raw sales_data."""

import argparse
import datetime as dt
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

if __package__:
    from .refresh_sales_monthly_summaries import METRICS, ROOT, TABLES, load_env
else:
    from refresh_sales_monthly_summaries import METRICS, ROOT, TABLES, load_env


def grain_comparison_sql(table, dimensions, extras, schema="public", source="public.sales_data"):
    columns = (*dimensions, *extras, *METRICS)
    expressions = (*dimensions, *extras.values(), *METRICS.values())
    selected = ", ".join(columns)
    projected = ", ".join(
        f"{expression} AS {column}" for column, expression in zip(columns, expressions)
    )
    return f"""WITH raw AS (
          SELECT {projected} FROM {source} s
          JOIN pg_temp.sales_validation_periods p USING (reporting_month, fiscal_year)
          GROUP BY {', '.join(dimensions)}
        ), stored AS (
          SELECT {selected} FROM {schema}.{table} s
          JOIN pg_temp.sales_validation_periods p USING (reporting_month, fiscal_year)
        ), differences AS (
          (SELECT {selected} FROM raw EXCEPT ALL SELECT {selected} FROM stored)
          UNION ALL
          (SELECT {selected} FROM stored EXCEPT ALL SELECT {selected} FROM raw)
        ) SELECT COUNT(*) FROM differences"""


def kpi_comparison_sql(schema="public", source="public.sales_data"):
    # This query intentionally spells out the dashboard's raw KPI formulas,
    # independently of the generic summary aggregation specification.
    return f"""WITH raw AS (
      SELECT p.reporting_month, p.fiscal_year,
        SUM(COALESCE(s.tp_sale_value,0)) gross_tp,
        SUM(COALESCE(s.net_sale_value,0)) net_sale,
        SUM(COALESCE(s.net_wo_reg_disc_value,0)) net_wo_reg,
        SUM(COALESCE(s.e_qty,0)) units,
        SUM(COALESCE(s.cyp,0)) cyp,
        SUM(COALESCE(s.discounts,0)) discounts,
        SUM(COALESCE(s.bonus_discount,0)) bonus_discount,
        COUNT(DISTINCT s.cust_number) FILTER (WHERE COALESCE(s.net_sale_value,0)>0) active_customers,
        COUNT(DISTINCT s.cust_number) transacting_customers,
        COUNT(DISTINCT s.position_code) FILTER (WHERE COALESCE(s.net_sale_value,0)>0) active_positions,
        COALESCE(SUM(ABS(COALESCE(s.net_sale_value,0))) FILTER
          (WHERE COALESCE(s.net_sale_value,0)<0),0) negative_returns
      FROM pg_temp.sales_validation_periods p
      LEFT JOIN {source} s USING (reporting_month, fiscal_year)
      GROUP BY p.reporting_month, p.fiscal_year
    ), stored AS (
      SELECT p.reporting_month, p.fiscal_year,
        COALESCE((SELECT SUM(COALESCE(x.gross_tp_value,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) gross_tp,
        COALESCE((SELECT SUM(COALESCE(x.net_sale_value,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) net_sale,
        COALESCE((SELECT SUM(COALESCE(x.net_wo_reg_disc_value,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) net_wo_reg,
        COALESCE((SELECT SUM(COALESCE(x.units,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) units,
        COALESCE((SELECT SUM(COALESCE(x.cyp,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) cyp,
        COALESCE((SELECT SUM(COALESCE(x.discounts,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) discounts,
        COALESCE((SELECT SUM(COALESCE(x.bonus_discount,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) bonus_discount,
        (SELECT COUNT(DISTINCT c.cust_number)
          FROM {schema}.sales_monthly_customer_summary c
          WHERE c.reporting_month=p.reporting_month AND c.fiscal_year=p.fiscal_year
            AND c.has_positive_sale) active_customers,
        (SELECT COUNT(DISTINCT c.cust_number)
          FROM {schema}.sales_monthly_customer_summary c
          WHERE c.reporting_month=p.reporting_month AND c.fiscal_year=p.fiscal_year) transacting_customers,
        (SELECT COUNT(DISTINCT x.position_code)
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year
            AND x.positive_sale_rows>0) active_positions,
        COALESCE((SELECT SUM(COALESCE(x.negative_net_sale_abs,0))
          FROM {schema}.sales_monthly_position_summary x
          WHERE x.reporting_month=p.reporting_month AND x.fiscal_year=p.fiscal_year),0) negative_returns
      FROM pg_temp.sales_validation_periods p
    )
    SELECT COUNT(*) FROM (
      (SELECT * FROM raw EXCEPT ALL SELECT * FROM stored)
      UNION ALL
      (SELECT * FROM stored EXCEPT ALL SELECT * FROM raw)
    ) differences"""


def distinct_comparison_sql(dimensions, schema="public", source="public.sales_data"):
    group_columns = ", ".join(dimensions)
    return f"""WITH raw AS (
      SELECT {group_columns},
        COUNT(DISTINCT s.cust_number) FILTER
          (WHERE COALESCE(s.net_sale_value,0)>0) AS active_customers,
        COUNT(DISTINCT s.cust_number) AS transacting_customers
      FROM {source} s
      JOIN pg_temp.sales_validation_periods p USING (reporting_month, fiscal_year)
      GROUP BY {group_columns}
    ), stored AS (
      SELECT {group_columns},
        COUNT(DISTINCT s.cust_number) FILTER
          (WHERE s.has_positive_sale) AS active_customers,
        COUNT(DISTINCT s.cust_number) AS transacting_customers
      FROM {schema}.sales_monthly_customer_summary s
      JOIN pg_temp.sales_validation_periods p USING (reporting_month, fiscal_year)
      GROUP BY {group_columns}
    )
    SELECT COUNT(*) FROM (
      (SELECT * FROM raw EXCEPT ALL SELECT * FROM stored)
      UNION ALL
      (SELECT * FROM stored EXCEPT ALL SELECT * FROM raw)
    ) differences"""


def validate(cursor, periods, schema="public", source="public.sales_data"):
    if not periods:
        return {"periods": 0, "grain_mismatches": {}, "kpi_mismatches": 0,
                "distinct_mismatches": {}, "source_row_mismatches": 0}
    cursor.execute(
        "CREATE TEMP TABLE sales_validation_periods ("
        "reporting_month text NOT NULL, fiscal_year text NOT NULL, "
        "PRIMARY KEY (reporting_month, fiscal_year)) ON COMMIT DROP"
    )
    execute_values(
        cursor,
        "INSERT INTO pg_temp.sales_validation_periods (reporting_month, fiscal_year) VALUES %s",
        periods,
    )
    mismatches = {}
    for table, dimensions, extras in TABLES:
        cursor.execute(grain_comparison_sql(table, dimensions, extras, schema, source))
        mismatches[table] = cursor.fetchone()[0]
    cursor.execute(kpi_comparison_sql(schema, source))
    kpi_mismatches = cursor.fetchone()[0]
    distinct_mismatches = {}
    for label, dimensions in (
        ("team", ("reporting_month", "fiscal_year", "team")),
        ("position", ("reporting_month", "fiscal_year", "team", "position_code")),
        ("product", ("reporting_month", "fiscal_year", "team", "product_no", "group_on")),
    ):
        cursor.execute(distinct_comparison_sql(dimensions, schema, source))
        distinct_mismatches[label] = cursor.fetchone()[0]
    cursor.execute(
        f"""SELECT COUNT(*) FROM (
          SELECT p.reporting_month, p.fiscal_year, COUNT(s.reporting_month) source_rows,
                 state.source_rows stored_rows
          FROM pg_temp.sales_validation_periods p
          LEFT JOIN {source} s USING (reporting_month, fiscal_year)
          LEFT JOIN {schema}.sales_monthly_summary_refresh_state state
            ON state.reporting_month=p.reporting_month AND state.fiscal_year=p.fiscal_year
          GROUP BY p.reporting_month, p.fiscal_year, state.source_rows
        ) counts WHERE stored_rows IS DISTINCT FROM source_rows"""
    )
    source_row_mismatches = cursor.fetchone()[0]
    return {"periods": len(periods), "grain_mismatches": mismatches,
            "kpi_mismatches": kpi_mismatches,
            "distinct_mismatches": distinct_mismatches,
            "source_row_mismatches": source_row_mismatches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", help="Optional reporting month, e.g. August,26")
    parser.add_argument("--fy", help="Fiscal year required with --month")
    parser.add_argument("--expect-db", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
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
        conn.set_session(isolation_level="REPEATABLE READ")
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != args.expect_db:
                raise RuntimeError("Database name mismatch")
            if args.month:
                periods = [(args.month, args.fy)]
            else:
                cursor.execute(
                    "SELECT reporting_month, fiscal_year "
                    "FROM public.sales_monthly_summary_refresh_state "
                    "ORDER BY fiscal_year, reporting_month"
                )
                periods = cursor.fetchall()
            report = validate(cursor, periods)
            conn.rollback()  # remove the session's temporary validation table
        print(report)
        if (any(report["grain_mismatches"].values()) or report["kpi_mismatches"]
                or any(report["distinct_mismatches"].values())
                or report["source_row_mismatches"]):
            raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
