import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MIGRATION = (ROOT / "db/migrations/004_dashboard_cache_invalidation.sql").read_text(
    encoding="utf-8"
)
ROLLBACK = (ROOT / "db/migrations/004_dashboard_cache_invalidation_rollback.sql").read_text(
    encoding="utf-8"
)


class CacheInvalidationMigrationTests(unittest.TestCase):
    def test_all_dashboard_sources_bump_shared_generation(self):
        for table in (
            "sales_data", "target_data", "staff_master", "call_data",
            "call_data_rollup", "sales_monthly_summary_refresh_state",
        ):
            self.assertIn(f"'{table}'", MIGRATION)
        for event in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            self.assertIn(event, MIGRATION)
        self.assertIn("generation = generation + 1", MIGRATION)

    def test_rollback_removes_triggers_function_and_generation_table(self):
        self.assertIn("DROP TRIGGER IF EXISTS", ROLLBACK)
        self.assertIn("DROP FUNCTION IF EXISTS public.bump_dashboard_cache_generation", ROLLBACK)
        self.assertIn("DROP TABLE IF EXISTS public.dashboard_cache_generation", ROLLBACK)


if __name__ == "__main__":
    unittest.main()
