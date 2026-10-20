import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = (ROOT / "db/migrations/005_sales_data_month_partition_PLAN.sql").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "db/migrations/005_sales_data_month_partition_ROLLBACK_PLAN.sql").read_text(encoding="utf-8")
SERVER = (ROOT / "scripts" / "server.py").read_text(encoding="utf-8")


class PartitioningPlanTests(unittest.TestCase):
    def test_partition_plan_is_guarded_and_not_applied_by_startup(self):
        self.assertIn("RAISE EXCEPTION 'PLAN ONLY", PLAN)
        self.assertIn("PARTITION BY RANGE (transaction_date)", PLAN)
        self.assertNotIn("005_sales_data_month_partition", SERVER)

    def test_rollback_plan_requires_write_replay_review(self):
        self.assertIn("RAISE EXCEPTION 'PLAN ONLY", ROLLBACK)
        self.assertIn("sales_data_unpartitioned_backup", ROLLBACK)
        self.assertIn("verify write replay", ROLLBACK)


if __name__ == "__main__":
    unittest.main()
