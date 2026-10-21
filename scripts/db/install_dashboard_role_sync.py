"""Align existing scoped dashboard account roles with staff designations."""

import argparse
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "db/migrations/012_sync_dashboard_roles_to_positions.sql"


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
    parser.add_argument("--expect-db", required=True, help="Exact destination database name")
    parser.add_argument("--apply", action="store_true", help="Apply; default prints the plan")
    args = parser.parse_args()
    print(f"Migration: {MIGRATION}")
    if not args.apply:
        print("Plan only; no database connection or changes made")
        return

    env = load_env(args.env_file)
    connection = psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env.get("DB_PASSWORD", ""), connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), to_regclass('public.dashboard_users'), to_regclass('public.staff_master')")
            database, users_table, staff_table = cursor.fetchone()
            if database != args.expect_db:
                raise RuntimeError("Database name mismatch; no migration applied")
            if not users_table or not staff_table:
                raise RuntimeError("dashboard_users and staff_master are required")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            print(f"Synchronized {cursor.rowcount} scoped account role(s).")
        connection.commit()
        print(f"Dashboard role sync installed in {database}.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
