import unittest
from pathlib import Path

import server


ROOT = Path(__file__).resolve().parents[1]


class ConnectionPoolTests(unittest.TestCase):
    def test_safe_pool_defaults_and_session_timeouts(self):
        self.assertEqual(server.DB_POOL_MIN, 1)
        self.assertEqual(server.DB_POOL_MAX, 5)
        self.assertEqual(server.DB_POOL_ACQUIRE_TIMEOUT_SECONDS, 5)
        self.assertEqual(server.DB_CONNECT_TIMEOUT_SECONDS, 5)
        self.assertIn(server.DB_STATEMENT_TIMEOUT_MS, (15000, 60000))
        self.assertEqual(server.DB_IDLE_TRANSACTION_TIMEOUT_MS, 30000)

    def test_post_import_maintenance_is_review_first(self):
        source = (ROOT / "db" / "post_import_maintenance.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument("--apply", action="store_true"', source)
        self.assertIn('parser.add_argument("--expect-db", required=True', source)
        self.assertIn('choices=("analyze", "vacuum-analyze")', source)
        self.assertIn('cursor.execute("SET lock_timeout = \'5s\'")', source)

    def test_application_startup_has_no_schema_ddl(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8").upper()
        for statement in ("CREATE TABLE", "CREATE INDEX", "ALTER TABLE", "DROP TABLE"):
            self.assertNotIn(statement, source)
        self.assertNotIn("ENSURE_DASHBOARD_INDEXES", source)


if __name__ == "__main__":
    unittest.main()
