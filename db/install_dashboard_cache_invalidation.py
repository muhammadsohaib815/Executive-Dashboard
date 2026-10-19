"""Install the dashboard cache generation triggers in one guarded transaction."""

import argparse
from pathlib import Path

import psycopg2

try:
    from .refresh_sales_monthly_summaries import ROOT, load_env
except ImportError:
    from refresh_sales_monthly_summaries import ROOT, load_env


MIGRATION = ROOT / "db/migrations/004_dashboard_cache_invalidation.sql"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--expect-db", help="Exact destination database name")
    parser.add_argument("--apply", action="store_true", help="Apply; default prints the plan")
    args = parser.parse_args()
    print(MIGRATION)
    if not args.apply:
        print("Plan only; no database connection or changes made")
        return
    if not args.expect_db:
        parser.error("--expect-db is required with --apply")
    env = load_env(args.env_file)
    connection = psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != args.expect_db:
                raise RuntimeError("Database name mismatch; no migration applied")
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(
                """SELECT count(*) FROM pg_trigger
                   WHERE tgname LIKE 'dashboard_cache_invalidate_%%'
                     AND NOT tgisinternal"""
            )
            if cursor.fetchone()[0] < 5:
                raise RuntimeError("Expected cache invalidation triggers were not installed")
        connection.commit()
        print("Cache invalidation migration committed")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
