import unittest
from pathlib import Path

from starlette.middleware.gzip import GZipMiddleware

from scripts import server


ROOT = Path(__file__).resolve().parents[1]
EXECUTIVE_JS = ROOT / "frontend" / "js"
SERVER_SOURCE = (ROOT / "scripts" / "server.py").read_text(encoding="utf-8")
API_SOURCE = (EXECUTIVE_JS / "api.js").read_text(encoding="utf-8")
AI_SOURCE = (EXECUTIVE_JS / "ai-insights.js").read_text(encoding="utf-8")


class PayloadOptimizationTests(unittest.TestCase):
    def test_large_responses_are_compressed(self):
        self.assertTrue(any(middleware.cls is GZipMiddleware for middleware in server.app.user_middleware))

    def test_manager_call_rows_are_limited_at_sql_level(self):
        manager_query = SERVER_SOURCE.split('manager_sql = f"""', 1)[1].split('"""', 1)[0]
        self.assertIn("LIMIT 10", manager_query)
        self.assertNotIn("LIMIT 50", manager_query)

    def test_hierarchy_payload_contains_only_ranking_candidates(self):
        self.assertIn("role_bottom_rank <= 10 OR role_top_rank <= 10", SERVER_SOURCE)
        self.assertIn("all_bottom_rank <= 10 OR all_top_rank <= 10", SERVER_SOURCE)
        self.assertIn("COUNT(*) OVER () AS total_count", SERVER_SOURCE)

    def test_product_and_discount_candidates_are_limited_in_sql(self):
        self.assertIn("achievement_bottom_rank <= 10 OR achievement_top_rank <= 10", SERVER_SOURCE)
        self.assertIn("discount_bottom_rank <= 10 OR discount_top_rank <= 10", SERVER_SOURCE)

    def test_duplicate_and_unused_kpi_arrays_are_not_serialized(self):
        self.assertNotIn('spo_sections["sku_performance"]', SERVER_SOURCE)
        self.assertNotIn('spo_sections["team_performance"]', SERVER_SOURCE)
        self.assertNotIn("sections.sku_performance", API_SOURCE)

    def test_frontend_deduplicates_identical_in_flight_requests(self):
        self.assertIn("const inFlightRequests = new Map()", API_SOURCE)
        self.assertIn("if (inFlightRequests.has(url))", API_SOURCE)
        self.assertIn("const inFlightRequests = new Map()", AI_SOURCE)
        self.assertIn("if (inFlightRequests.has(url))", AI_SOURCE)


if __name__ == "__main__":
    unittest.main()
