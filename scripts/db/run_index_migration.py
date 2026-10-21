"""Run dashboard index migrations one statement at a time in autocommit mode."""

import argparse
from pathlib import Path
import re

import psycopg2


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = {
    "001": ROOT / "db/migrations/001_existing_dashboard_indexes.sql",
    "002": ROOT / "db/migrations/002_sales_query_indexes.sql",
    "002-rollback": ROOT / "db/migrations/002_sales_query_indexes_rollback.sql",
    "007": ROOT / "db/migrations/007_call_performance_indexes.sql",
    "007-rollback": ROOT / "db/migrations/007_call_performance_indexes_rollback.sql",
}
NEW_INDEX_SIGNATURES = {
    "idx_sales_data_product_month": ("(product_no, reporting_month)", False),
    "idx_sales_data_first_buy_positive": (
        "(position_code, cust_number, reporting_month)", True
    ),
    "idx_fmcg_cust_call_month_ff": ("(month, ff_id)", False),
    "idx_fmcg_exception_month_ff": ("(month, ff_id)", False),
    "idx_pharma_provider_calls_month_ff": ("(month, ff_id)", False),
}
INDEX_TABLES = {
    "idx_sales_data_product_month": "sales_data",
    "idx_sales_data_first_buy_positive": "sales_data",
    "idx_fmcg_cust_call_month_ff": "fmcg_cust_call",
    "idx_fmcg_exception_month_ff": "fmcg_exception",
    "idx_pharma_provider_calls_month_ff": "pharma_provider_calls",
}


def load_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def statements(path):
    """Accept only the concurrent index DDL used by these migration files."""
    source = "\n".join(
        line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()
    )
    commands = [part.strip() for part in source.split(";") if part.strip()]
    if not commands or not source.rstrip().endswith(";"):
        raise ValueError("Migration must contain semicolon-terminated statements")
    for command in commands:
        if not re.fullmatch(
            r"(?:CREATE INDEX CONCURRENTLY IF NOT EXISTS \w+ ON public\.\w+ .+|"
            r"DROP INDEX CONCURRENTLY IF EXISTS public\.\w+)",
            command, re.IGNORECASE | re.DOTALL,
        ):
            raise ValueError("Only concurrent public-schema index DDL is permitted")
    return commands


def index_details(cursor, name):
    cursor.execute(
        """SELECT table_rel.relname, idx.indisvalid, idx.indisready,
                  pg_get_indexdef(index_rel.oid)
           FROM pg_class index_rel
           JOIN pg_namespace ns ON ns.oid = index_rel.relnamespace
           JOIN pg_index idx ON idx.indexrelid = index_rel.oid
           JOIN pg_class table_rel ON table_rel.oid = idx.indrelid
           WHERE ns.nspname = 'public' AND index_rel.relname = %s""",
        [name],
    )
    return cursor.fetchone()


def check_index(cursor, name, table):
    details = index_details(cursor, name)
    if details is None:
        return False
    actual_table, valid, ready, definition = details
    if actual_table != table or not valid or not ready:
        raise RuntimeError(f"Existing index {name} is on the wrong table or is invalid")
    if name in NEW_INDEX_SIGNATURES:
        columns, partial = NEW_INDEX_SIGNATURES[name]
        normalized = re.sub(r"\s+", " ", definition.lower())
        if columns not in normalized or (" where " in normalized) != partial:
            raise RuntimeError(f"Existing index {name} has a different definition")
        if partial and not all(part in normalized for part in ("coalesce", "net_sale_value", ">")):
            raise RuntimeError(f"Existing index {name} has a different predicate")
    return True


def command_target(command):
    create = re.match(
        r"CREATE INDEX CONCURRENTLY IF NOT EXISTS (\w+) ON public\.(\w+)",
        command, re.IGNORECASE,
    )
    if create:
        return "create", create.group(1), create.group(2)
    drop = re.match(r"DROP INDEX CONCURRENTLY IF EXISTS public\.(\w+)", command, re.IGNORECASE)
    name = drop.group(1)
    return "drop", name, INDEX_TABLES.get(name, "sales_data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration", choices=MIGRATIONS, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--expect-db", required=True, help="Exact database name to guard against mistakes")
    parser.add_argument("--apply", action="store_true", help="Execute the reviewed migration")
    args = parser.parse_args()
    commands = statements(MIGRATIONS[args.migration])
    for command in commands:
        action, name, _ = command_target(command)
        print(f"{action}: {name}")
    if not args.apply:
        print("Plan only; no database connection or changes made")
        return

    env = load_env(args.env_file)
    conn = psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10,
    )
    try:
        conn.autocommit = True  # CREATE/DROP INDEX CONCURRENTLY must not run in a transaction.
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_setting('transaction_read_only')")
            database, read_only = cursor.fetchone()
            if database != args.expect_db or read_only != "off":
                raise RuntimeError("Database name mismatch or connection is read-only")
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("SET statement_timeout = '30min'")
            for command in commands:
                action, name, table = command_target(command)
                exists = check_index(cursor, name, table)
                if action == "drop" and not exists:
                    print(f"already absent: {name}")
                    continue
                if action == "create" and exists:
                    print(f"already valid: {name}")
                    continue
                cursor.execute(command)
                if action == "create":
                    if not check_index(cursor, name, table):
                        raise RuntimeError(f"Index {name} was not visible after creation")
                print(f"completed: {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
