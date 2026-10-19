"""Plan or run bounded PostgreSQL statistics maintenance after dashboard imports."""

import argparse
from pathlib import Path

import psycopg2
from psycopg2 import sql


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TABLES = (
    "sales_data", "target_data", "staff_master", "call_data_rollup",
    "sales_monthly_position_summary", "sales_monthly_product_summary",
    "sales_monthly_customer_summary", "sales_monthly_position_product_summary",
)


def load_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-db", required=True, help="Exact database name safety check")
    parser.add_argument("--apply", action="store_true", help="Execute; otherwise print the plan")
    parser.add_argument(
        "--mode", choices=("analyze", "vacuum-analyze"), default="analyze",
        help="Use vacuum-analyze only after delete-heavy or replacement imports",
    )
    parser.add_argument("--tables", nargs="+", choices=DEFAULT_TABLES, default=list(DEFAULT_TABLES))
    return parser.parse_args()


def main():
    args = parse_args()
    env = load_env(ROOT / ".env")
    if args.expect_db != env["DB_NAME"]:
        raise SystemExit("Database safety check failed: --expect-db does not match DB_NAME")
    operation = "VACUUM (ANALYZE)" if args.mode == "vacuum-analyze" else "ANALYZE"
    print(f"Database: {args.expect_db}")
    print(f"Mode: {operation}")
    for table in args.tables:
        print(f"  {operation} public.{table}")
    if not args.apply:
        print("Plan only. Add --apply after review.")
        return

    connection = psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10,
        application_name="dashboard-post-import-maintenance",
    )
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET statement_timeout = '30min'")
            cursor.execute("SET lock_timeout = '5s'")
            for table in args.tables:
                command = sql.SQL("{} public.{}").format(
                    sql.SQL(operation), sql.Identifier(table),
                )
                cursor.execute(command)
                print(f"Completed: {operation} public.{table}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
