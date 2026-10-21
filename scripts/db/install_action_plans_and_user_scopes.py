"""Install staff hierarchy assignments, action plans, and notification tables."""

import argparse
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "db/migrations/008_action_plans_and_user_scopes.sql"


def load_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--expect-db", help="Exact destination database name")
    parser.add_argument("--apply", action="store_true", help="Apply; default prints the plan")
    args = parser.parse_args()
    print(f"Migration: {MIGRATION}")
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
            cursor.execute("SELECT current_database(), to_regclass('public.dashboard_users'), to_regclass('public.staff_master'), to_regprocedure('public.bump_dashboard_cache_generation()')")
            database, users, staff, cache_trigger = cursor.fetchone()
            if database != args.expect_db:
                raise RuntimeError("Database name mismatch; no migration applied")
            if not users or not staff or not cache_trigger:
                raise RuntimeError("Required dashboard_users, staff_master, or cache invalidation schema is missing")
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            cursor.execute(
                """SELECT to_regclass('public.dashboard_action_plans'),
                          to_regclass('public.dashboard_action_plan_recipients'),
                          to_regclass('public.dashboard_notifications')"""
            )
            if not all(cursor.fetchone()):
                raise RuntimeError("Action plan schema verification failed")
        connection.commit()
        print(f"Hierarchy and notification schema installed in {database}.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
