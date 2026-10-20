import unittest
from unittest.mock import patch

from scripts import server


class SummaryFreshnessGateTests(unittest.TestCase):
    def test_missing_tables_keep_raw_query_path(self):
        with patch.object(server, "query", return_value=[(None,) * 6]):
            self.assertFalse(server.sales_summaries_ready())

    def test_requested_period_must_be_refreshed_and_clean(self):
        calls = iter([
            [("position", "product", "customer", "position_product", "state", "dirty")],
            [(False,)],
        ])
        with patch.object(server, "query", side_effect=lambda *args, **kwargs: next(calls)):
            self.assertFalse(server.sales_summaries_ready([("August,26", "2026-27")]))

    def test_clean_complete_snapshot_enables_summaries(self):
        calls = iter([
            [("position", "product", "customer", "position_product", "state", "dirty")],
            [(True,)],
        ])
        with patch.object(server, "query", side_effect=lambda *args, **kwargs: next(calls)):
            self.assertTrue(server.sales_summaries_ready())


if __name__ == "__main__":
    unittest.main()
