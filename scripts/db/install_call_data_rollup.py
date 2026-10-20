"""Install and backfill the dashboard's PostgreSQL call-data rollup."""
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parents[2]


def load_env():
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main():
    env = load_env()
    with psycopg2.connect(
        host=env["DB_HOST"], port=int(env["DB_PORT"]),
        dbname=env["DB_NAME"], user=env["DB_USER"], password=env["DB_PASSWORD"],
    ) as conn:
        with conn.cursor() as cur:
            # Hold writes during the backfill, then install triggers and commit
            # together so no call_data change can be missed.
            cur.execute("LOCK TABLE call_data IN SHARE ROW EXCLUSIVE MODE")
            cur.execute((ROOT / "db" / "call_data_rollup.sql").read_text(encoding="utf-8"))
            cur.execute((ROOT / "db" / "call_data_rollup_triggers.sql").read_text(encoding="utf-8"))
            cur.execute("CALL refresh_call_data_rollup()")
            cur.execute("SELECT kind, COUNT(*) FROM call_data_rollup GROUP BY kind ORDER BY kind")
            print("Call rollup ready:", dict(cur.fetchall()))


if __name__ == "__main__":
    main()
