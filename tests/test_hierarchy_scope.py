"""Tests for request-scoped hierarchy resolution."""
import unittest
from unittest.mock import patch

import server


class HierarchyScopeTests(unittest.TestCase):
    def test_resolver_deduplicates_and_discards_null_positions(self):
        with patch.object(server, "query", return_value=[("P2",), ("P1",), ("P2",), (None,)]) as execute:
            positions = server.resolve_authorized_positions(
                "ASM", "All", "All", "All", team="FMCG",
            )

        self.assertEqual(positions, ["P2", "P1"])
        sql, params, query_id = execute.call_args.args
        self.assertIn("WITH RECURSIVE scope", sql)
        self.assertIn("SELECT DISTINCT position_code FROM scope", sql)
        self.assertEqual(params, ["ASM"])
        self.assertEqual(query_id, "hierarchy.authorized_scope")

    def test_resolved_scope_uses_one_deduplicated_array_parameter(self):
        sql, params = server.scope_cte(
            "ASM", "All", "All", "All", team="COMBINED",
            target_suffix="aug_26", resolved_positions=["P1", "P1", "P2", None],
        )

        self.assertIn("unnest(%s::text[])", sql)
        self.assertNotIn("JOIN scope s ON m.report_to_position_code", sql)
        self.assertEqual(params, [["P1", "P2"]])

    def test_empty_resolved_scope_remains_empty(self):
        sql, params = server.scope_cte(
            "SPO", "All", "All", "All", resolved_positions=[],
        )

        self.assertIn("unnest(%s::text[])", sql)
        self.assertEqual(params, [[]])

    def test_role_scope_modes_preserve_existing_permission_rules(self):
        recursive_roles = ("EXEC", "DGM", "RSM", "ASM")
        for role in recursive_roles:
            sql, _ = server.hierarchy_scope_cte(role, "All", "All", "All")
            self.assertTrue(sql.startswith("WITH RECURSIVE scope"), role)

        for role in ("ALL", "MIO", "SPO", "PS", "SB", "ASMTE", "CM", "SPOWS", "TE"):
            sql, _ = server.hierarchy_scope_cte(role, "All", "All", "All")
            self.assertTrue(sql.startswith("WITH scope"), role)
            self.assertNotIn("WITH RECURSIVE", sql, role)

        national_hod, _ = server.hierarchy_scope_cte("HOD", "All", "All", "All")
        territory_hod, _ = server.hierarchy_scope_cte(
            "HOD", "All", "All", "All", territory="T1",
        )
        self.assertNotIn("WITH RECURSIVE", national_hod)
        self.assertIn("WITH RECURSIVE", territory_hod)

    def test_reporting_tree_is_cycle_safe_and_deduplicated(self):
        with patch.object(server, "query", return_value=[("ASM1",), ("SPO1",)]) as execute:
            positions = server.resolve_reporting_tree("ASM1")

        self.assertEqual(positions, ["ASM1", "SPO1"])
        sql, params, query_id = execute.call_args.args
        self.assertIn(" UNION\n", sql)
        self.assertNotIn("UNION ALL", sql)
        self.assertIn("SELECT DISTINCT position_code", sql)
        self.assertEqual(params, ["ASM1"])
        self.assertEqual(query_id, "hierarchy.reporting_tree")


if __name__ == "__main__":
    unittest.main()
