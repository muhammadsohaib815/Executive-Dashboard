"""Coverage for the Dept Terr Code staff-master lookup."""
import unittest
from unittest.mock import patch

import server


class TerritoryScopeTests(unittest.TestCase):
    def test_returns_all_matching_staff_records_and_normalizes_input(self):
        row = (
            "P-01", "A. Khan", "SPO", "FAST MOVING CONSUMER GOODS",
            "ABT-01", "North", "Zone A", "Sub Zone 1", "FMCG",
        )
        with patch.object(server, "query", return_value=[row]) as execute:
            response = server.territory_scope("  ABT-01  ")

        self.assertEqual(response["records"], [{
            "position_code": "P-01", "employee": "A. Khan", "designation": "SPO",
            "team": "FAST MOVING CONSUMER GOODS", "territory": "ABT-01",
            "region": "North", "zone": "Zone A", "subzone": "Sub Zone 1",
            "team_filter": "FMCG",
        }])
        sql, params, query_id = execute.call_args.args
        self.assertIn("TRIM(dept_territory_code) = %s", sql)
        self.assertEqual(params, ["ABT-01"])
        self.assertEqual(query_id, "filters.territory_scope")

    def test_scope_predicates_normalize_filter_values(self):
        sql, params = server.hierarchy_scope_cte(
            "ALL", " North ", " Zone A ", " Sub Zone 1 ", territory=" ABT-01 ",
        )

        self.assertIn("TRIM(region_name) = %s", sql)
        self.assertIn("TRIM(dept_territory_code) = %s", sql)
        self.assertEqual(params, ["North", "Zone A", "Sub Zone 1", "ABT-01"])


if __name__ == "__main__":
    unittest.main()
