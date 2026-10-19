"""Install the reviewed monthly summary migration in one guarded transaction."""

import argparse
from pathlib import Path
import re

import psycopg2

if __package__:
    from .refresh_sales_monthly_summaries import METRICS, ROOT, SOURCE_COLUMNS, TABLES, load_env
else:
    from refresh_sales_monthly_summaries import METRICS, ROOT, SOURCE_COLUMNS, TABLES, load_env


MIGRATION = ROOT / "db/migrations/003_sales_monthly_summaries.sql"


def check_source_schema(cursor):
    cursor.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'sales_data'"""
    )
    existing = dict(cursor.fetchall())
    missing = set(SOURCE_COLUMNS) - set(existing)
    if missing:
        raise RuntimeError("sales_data schema is missing required summary columns: "
                           + ", ".join(sorted(missing)))
    numeric = {"tp_sale_value", "net_sale_value", "net_wo_reg_disc_value", "e_qty",
               "net_qty", "cyp", "discounts", "bonus_discount", "mnp_commission",
               "net_value"}
    wrong_type = [column for column in SOURCE_COLUMNS
                  if existing[column] != ("numeric" if column in numeric else "text")]
    if wrong_type:
        raise RuntimeError("sales_data column types differ from the reviewed schema: "
                           + ", ".join(wrong_type))


def check_installed_schema(cursor, schema="public"):
    if schema == "pg_temp":
        cursor.execute("SELECT nspname FROM pg_namespace WHERE oid = pg_my_temp_schema()")
        schema = cursor.fetchone()[0]
    for table, dimensions, extras in TABLES:
        cursor.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = %s AND table_name = %s""",
            [schema, table],
        )
        columns = {row[0] for row in cursor.fetchall()}
        expected = set(dimensions) | set(extras) | set(METRICS)
        if columns != expected:
            raise RuntimeError(f"Existing {table} has an unexpected column layout")
        cursor.execute(
            """SELECT idx.indisunique, idx.indisvalid, idx.indnullsnotdistinct,
                      pg_get_indexdef(index_rel.oid)
               FROM pg_class index_rel
               JOIN pg_namespace ns ON ns.oid = index_rel.relnamespace
               JOIN pg_index idx ON idx.indexrelid = index_rel.oid
               JOIN pg_class table_rel ON table_rel.oid = idx.indrelid
               WHERE ns.nspname = %s AND index_rel.relname = %s
                 AND table_rel.relname = %s""",
            [schema, f"{table}_grain", table],
        )
        index = cursor.fetchone()
        if not index:
            raise RuntimeError(f"Missing unique grain index on {table}")
        unique, valid, nulls_not_distinct, definition = index
        normalized = re.sub(r"\s+", " ", definition.lower())
        if (not unique or not valid or not nulls_not_distinct
                or f"({', '.join(dimensions)})" not in normalized):
            raise RuntimeError(f"Existing unique grain index on {table} differs from migration")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--expect-db", help="Exact destination database name")
    parser.add_argument("--apply", action="store_true", help="Run the migration; default is a dry plan")
    args = parser.parse_args()
    print(MIGRATION)
    print("Summary tables:", ", ".join(table for table, _, _ in TABLES))
    if not args.apply:
        print("Plan only; no database connection or changes made")
        return
    if not args.expect_db:
        parser.error("--expect-db is required with --apply")
    env = load_env(args.env_file)
    conn = psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_setting('server_version_num')::int")
            database, version = cursor.fetchone()
            if database != args.expect_db:
                raise RuntimeError("Database name mismatch; no migration applied")
            if version < 150000:
                raise RuntimeError("PostgreSQL 15 or newer is required for NULLS NOT DISTINCT")
            check_source_schema(cursor)
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute("SET LOCAL statement_timeout = '10min'")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            check_installed_schema(cursor)
            cursor.execute(
                """SELECT count(*) FROM pg_trigger
                   WHERE tgrelid = 'public.sales_data'::regclass
                     AND tgname LIKE 'sales_monthly_summary_dirty_%%'
                     AND NOT tgisinternal"""
            )
            if cursor.fetchone()[0] != 4:
                raise RuntimeError("Expected four sales_data change triggers")
        conn.commit()
        print("Migration committed; run the --all backfill next")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
