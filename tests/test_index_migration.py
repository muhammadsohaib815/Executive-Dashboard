"""Static safety checks for the index migration; no database writes."""

import unittest

from scripts.db.run_index_migration import MIGRATIONS, check_index, command_target, statements


class _CatalogCursor:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params):
        self.params = params

    def fetchone(self):
        return self.row


class IndexMigrationTests(unittest.TestCase):
    def test_baseline_carries_all_existing_startup_indexes(self):
        commands = statements(MIGRATIONS["001"])
        self.assertEqual(len(commands), 20)
        self.assertEqual(len({command_target(command)[1] for command in commands}), 20)
        self.assertTrue(all("CREATE INDEX CONCURRENTLY IF NOT EXISTS" in command for command in commands))

    def test_new_indexes_and_rollback_are_separate(self):
        created = {command_target(command)[1] for command in statements(MIGRATIONS["002"])}
        dropped = {command_target(command)[1] for command in statements(MIGRATIONS["002-rollback"])}
        self.assertEqual(created, {
            "idx_sales_data_product_month", "idx_sales_data_first_buy_positive",
        })
        self.assertEqual(created, dropped)
        self.assertTrue(all("CONCURRENTLY" in command for command in statements(MIGRATIONS["002-rollback"])))

    def test_existing_wrong_definition_or_invalid_index_is_rejected(self):
        valid = _CatalogCursor(("sales_data", True, True,
            "CREATE INDEX idx_sales_data_product_month ON public.sales_data USING btree (product_no, reporting_month)"))
        self.assertTrue(check_index(valid, "idx_sales_data_product_month", "sales_data"))
        wrong = _CatalogCursor(("sales_data", True, True,
            "CREATE INDEX idx_sales_data_product_month ON public.sales_data USING btree (reporting_month)"))
        with self.assertRaises(RuntimeError):
            check_index(wrong, "idx_sales_data_product_month", "sales_data")
        invalid = _CatalogCursor(("sales_data", False, True,
            "CREATE INDEX idx_sales_data_product_month ON public.sales_data USING btree (product_no, reporting_month)"))
        with self.assertRaises(RuntimeError):
            check_index(invalid, "idx_sales_data_product_month", "sales_data")

    def test_call_performance_indexes_and_rollback_are_separate(self):
        created = {command_target(command)[1] for command in statements(MIGRATIONS["007"])}
        dropped = {command_target(command)[1] for command in statements(MIGRATIONS["007-rollback"])}
        self.assertEqual(created, {
            "idx_fmcg_cust_call_month_ff", "idx_fmcg_exception_month_ff",
            "idx_pharma_provider_calls_month_ff",
        })
        self.assertEqual(created, dropped)


if __name__ == "__main__":
    unittest.main()
