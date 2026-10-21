"""Install the dashboard authentication table.

Run once after deploying the migration:
    python scripts/db/install_dashboard_auth.py
"""
from pathlib import Path
import sys

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.server import ENV  # noqa: E402


def main():
    migration = (ROOT / "db" / "migrations" / "006_dashboard_auth.sql").read_text(encoding="utf-8")
    conn = psycopg2.connect(
        host=ENV["DB_HOST"], port=int(ENV["DB_PORT"]), dbname=ENV["DB_NAME"],
        user=ENV["DB_USER"], password=ENV["DB_PASSWORD"],
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(migration)
        conn.commit()
        print("Dashboard authentication schema installed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
