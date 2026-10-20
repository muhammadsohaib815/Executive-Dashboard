"""Validate monthly summary grains using session-local PostgreSQL tables."""

import re
import unittest

import psycopg2

from scripts.db.install_sales_monthly_summaries import check_installed_schema
from scripts.db.refresh_sales_monthly_summaries import (
    METRICS, ROOT, SOURCE_COLUMNS, TABLES, insert_sql, load_env,
    periods_to_refresh, refresh_periods,
)
from scripts.db.validate_sales_monthly_summaries import validate


MIGRATION = (ROOT / "db/migrations/003_sales_monthly_summaries.sql").read_text(
    encoding="utf-8"
)


class SalesMonthlySummaryTests(unittest.TestCase):
    def test_grains_and_change_events_are_declared(self):
        for table, dimensions, extras in TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS public.{table}", MIGRATION)
            self.assertIn(f"{table}_grain", MIGRATION)
            sql = insert_sql(table, dimensions, extras)
            for metric in METRICS:
                self.assertIn(metric, sql)
        self.assertEqual(MIGRATION.count("NULLS NOT DISTINCT;"), 4)
        for event in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            self.assertIn(f"AFTER {event} ON public.sales_data", MIGRATION)

    def test_refresh_and_correction_with_overlapping_customers(self):
        env_path = ROOT / ".env"
        if not env_path.exists():
            self.skipTest("No PostgreSQL test connection configured")
        env = load_env(env_path)
        try:
            conn = psycopg2.connect(
                host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
                user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=5,
            )
        except psycopg2.OperationalError:
            self.skipTest("PostgreSQL connection unavailable")
        try:
            conn.set_session(isolation_level="REPEATABLE READ")
            with conn.cursor() as cursor:
                cursor.execute(
                    "CREATE TEMP TABLE sales_data ("
                    + ", ".join(
                        f"{column} {'numeric' if column in {'tp_sale_value', 'net_sale_value', 'net_wo_reg_disc_value', 'e_qty', 'net_qty', 'cyp', 'discounts', 'bonus_discount', 'mnp_commission', 'net_value'} else 'text'}"
                        for column in SOURCE_COLUMNS
                    ) + ")"
                )
                for table, _, _ in TABLES:
                    body = re.search(
                        rf"CREATE TABLE IF NOT EXISTS public\.{table} \((.*?)\);",
                        MIGRATION, re.DOTALL,
                    ).group(1)
                    cursor.execute(f"CREATE TEMP TABLE {table} ({body})")
                for table in ("sales_monthly_summary_refresh_state",
                              "sales_monthly_summary_dirty_period"):
                    body = re.search(
                        rf"CREATE TABLE IF NOT EXISTS public\.{table} \((.*?)\);",
                        MIGRATION, re.DOTALL,
                    ).group(1)
                    cursor.execute(f"CREATE TEMP TABLE {table} ({body})")
                cursor.execute(
                    """INSERT INTO pg_temp.sales_data
                      (reporting_month,fiscal_year,team,position_code,product_no,
                       group_on,cust_number,cust_name,prd_name,tp_sale_value,
                       net_sale_value,net_wo_reg_disc_value,e_qty,net_qty,cyp,
                       discounts,bonus_discount,mnp_commission,net_value)
                      VALUES
                      ('July,26','2026-27','FAST MOVING CONSUMER GOODS','A','X','G','C1','One','X',120,100,95,10,10,1,5,2,1,100),
                      ('July,26','2026-27','FAST MOVING CONSUMER GOODS','A','Y','G','C1','One','Y',60,50,48,5,5,0.5,2,1,1,50),
                      ('July,26','2026-27','FAST MOVING CONSUMER GOODS','B','X','G','C1','One','X',24,20,19,2,2,0.2,1,0,0,20),
                      ('July,26','2026-27','FAST MOVING CONSUMER GOODS','B','X','G','C2','Two','X',-12,-10,-10,-1,-1,-0.1,0,0,0,-10)"""
                )
                period = [("July,26", "2026-27")]
                refresh_periods(cursor, period, schema="pg_temp", source="pg_temp.sales_data")
                report = validate(cursor, period, schema="pg_temp", source="pg_temp.sales_data")
                self.assertEqual(report["kpi_mismatches"], 0)
                self.assertEqual(report["source_row_mismatches"], 0)
                self.assertFalse(any(report["grain_mismatches"].values()))
                cursor.execute(
                    "SELECT SUM(active_customer_count) FROM pg_temp.sales_monthly_position_summary"
                )
                self.assertGreater(cursor.fetchone()[0], 1)
                cursor.execute(
                    "SELECT COUNT(DISTINCT cust_number) FROM pg_temp.sales_monthly_customer_summary WHERE has_positive_sale"
                )
                self.assertEqual(cursor.fetchone()[0], 1)
            conn.commit()
            with conn.cursor() as cursor:
                cursor.execute("UPDATE pg_temp.sales_data SET net_sale_value=30 WHERE position_code='B' AND cust_number='C1'")
                cursor.execute("DELETE FROM pg_temp.sales_data WHERE cust_number='C2'")
                cursor.execute(
                    "INSERT INTO pg_temp.sales_monthly_summary_dirty_period "
                    "(reporting_month,fiscal_year) VALUES ('July,26','2026-27')"
                )
                dirty = periods_to_refresh(cursor, "dirty", schema="pg_temp")
                self.assertEqual(dirty, [("July,26", "2026-27")])
                refresh_periods(cursor, dirty,
                                schema="pg_temp", source="pg_temp.sales_data")
                report = validate(cursor, [("July,26", "2026-27")],
                                  schema="pg_temp", source="pg_temp.sales_data")
                self.assertFalse(any(report["grain_mismatches"].values()))
                self.assertEqual(report["kpi_mismatches"], 0)
                cursor.execute("SELECT SUM(transaction_count) FROM pg_temp.sales_monthly_position_summary")
                self.assertEqual(cursor.fetchone()[0], 3)
                self.assertEqual(periods_to_refresh(cursor, "dirty", schema="pg_temp"), [])
            conn.commit()
            with conn.cursor() as cursor:
                refresh_periods(cursor, [("July,26", "2026-27")],
                                schema="pg_temp", source="pg_temp.sales_data")
                cursor.execute("SELECT SUM(transaction_count) FROM pg_temp.sales_monthly_position_summary")
                self.assertEqual(cursor.fetchone()[0], 3)
            conn.commit()
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM pg_temp.sales_data")
                counts = refresh_periods(cursor, [("July,26", "2026-27")],
                                         schema="pg_temp", source="pg_temp.sales_data")
                self.assertEqual(counts[("July,26", "2026-27")], 0)
                report = validate(cursor, [("July,26", "2026-27")],
                                  schema="pg_temp", source="pg_temp.sales_data")
                self.assertFalse(any(report["grain_mismatches"].values()))
                self.assertEqual(report["kpi_mismatches"], 0)
                cursor.execute("SELECT COUNT(*) FROM pg_temp.sales_monthly_customer_summary")
                self.assertEqual(cursor.fetchone()[0], 0)
            conn.rollback()
        finally:
            conn.close()

    def test_migration_triggers_track_insert_update_delete_and_truncate(self):
        env_path = ROOT / ".env"
        if not env_path.exists():
            self.skipTest("No PostgreSQL test connection configured")
        env = load_env(env_path)
        try:
            conn = psycopg2.connect(
                host=env["DB_HOST"], port=int(env["DB_PORT"]), dbname=env["DB_NAME"],
                user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=5,
            )
        except psycopg2.OperationalError:
            self.skipTest("PostgreSQL connection unavailable")
        try:
            with conn.cursor() as cursor:
                cursor.execute("CREATE TEMP TABLE sales_data (reporting_month text, fiscal_year text)")
                cursor.execute(MIGRATION.replace("public.", "pg_temp."))
                cursor.execute(MIGRATION.replace("public.", "pg_temp."))
                check_installed_schema(cursor, "pg_temp")
                cursor.execute(
                    "INSERT INTO pg_temp.sales_data VALUES ('July,26','2026-27')"
                )
                cursor.execute(
                    "UPDATE pg_temp.sales_data SET reporting_month='August,26'"
                )
                cursor.execute(
                    "SELECT reporting_month FROM pg_temp.sales_monthly_summary_dirty_period ORDER BY 1"
                )
                self.assertEqual([row[0] for row in cursor.fetchall()],
                                 ["August,26", "July,26"])
                cursor.execute("DELETE FROM pg_temp.sales_data")
                cursor.execute(
                    "INSERT INTO pg_temp.sales_monthly_summary_refresh_state "
                    "(reporting_month,fiscal_year,source_rows,refreshed_at) "
                    "VALUES ('September,26','2026-27',1,clock_timestamp())"
                )
                cursor.execute("TRUNCATE pg_temp.sales_data")
                cursor.execute(
                    "SELECT reporting_month FROM pg_temp.sales_monthly_summary_dirty_period ORDER BY 1"
                )
                self.assertEqual([row[0] for row in cursor.fetchall()],
                                 ["August,26", "July,26", "September,26"])
            conn.rollback()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
