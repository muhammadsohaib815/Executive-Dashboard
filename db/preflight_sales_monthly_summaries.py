"""Build and validate one real month in session-local tables; leave public tables unchanged."""

import argparse
import datetime as dt
from pathlib import Path
import re
import time

import psycopg2

if __package__:
    from .refresh_sales_monthly_summaries import ROOT, TABLES, load_env, refresh_periods
    from .validate_sales_monthly_summaries import validate
else:
    from refresh_sales_monthly_summaries import ROOT, TABLES, load_env, refresh_periods
    from validate_sales_monthly_summaries import validate


MIGRATION = ROOT / "db/migrations/003_sales_monthly_summaries.sql"


def create_temporary_schema(cursor):
    source = MIGRATION.read_text(encoding="utf-8")
    tables = [table for table, _, _ in TABLES] + [
        "sales_monthly_summary_refresh_state",
        "sales_monthly_summary_dirty_period",
    ]
    for table in tables:
        match = re.search(
            rf"CREATE TABLE IF NOT EXISTS public\.{table} \((.*?)\);",
            source, re.DOTALL,
        )
        if match is None:
            raise RuntimeError(f"Missing migration definition for {table}")
        cursor.execute(f"CREATE TEMP TABLE {table} ({match.group(1)})")
    for name, table, columns in re.findall(
        r"CREATE UNIQUE INDEX IF NOT EXISTS (\w+)\s+ON public\.(\w+)\s+"
        r"\((.*?)\) NULLS NOT DISTINCT;",
        source, re.DOTALL,
    ):
        cursor.execute(f"CREATE UNIQUE INDEX {name} ON pg_temp.{table} ({columns}) NULLS NOT DISTINCT")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="Reporting month, e.g. August,26")
    parser.add_argument("--fy", required=True, help="Fiscal year, e.g. 2026-27")
    parser.add_argument("--expect-db", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
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
                raise RuntimeError("Database name mismatch; no preflight performed")
            create_temporary_schema(cursor)
            periods = [(args.month, args.fy)]
            start = time.perf_counter()
            counts = refresh_periods(cursor, periods, schema="pg_temp")
            refresh_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            report = validate(cursor, periods, schema="pg_temp")
            validation_ms = (time.perf_counter() - start) * 1000
            summary_counts = {}
            for table, _, _ in TABLES:
                cursor.execute(f"SELECT COUNT(*) FROM pg_temp.{table}")
                summary_counts[table] = cursor.fetchone()[0]
            print("Source rows:", counts[periods[0]])
            print("Summary rows:", summary_counts)
            print("Refresh ms:", round(refresh_ms, 1))
            print("Validation ms:", round(validation_ms, 1))
            print("Validation:", report)
            if (any(report["grain_mismatches"].values())
                    or report["kpi_mismatches"]
                    or any(report["distinct_mismatches"].values())
                    or report["source_row_mismatches"]):
                raise RuntimeError("Preflight validation failed")
        conn.rollback()  # remove all temporary data
        print("Preflight passed; no permanent tables changed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
