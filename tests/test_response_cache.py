import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import server
from response_cache import TTLResponseCache


class ResponseCacheTests(unittest.TestCase):
    def test_ttl_and_lru_bound(self):
        now = [0.0]
        cache = TTLResponseCache(ttl_seconds=10, max_entries=2, clock=lambda: now[0])
        cache.set("a", 1)
        cache.set("b", 2)
        self.assertEqual(cache.get("a"), (True, 1))
        cache.set("c", 3)
        self.assertEqual(cache.get("b"), (False, None))
        now[0] = 11.0
        self.assertEqual(cache.get("a"), (False, None))
        stats = cache.stats()
        self.assertEqual(stats["entries"], 1)
        self.assertEqual(stats["evictions"], 1)
        self.assertEqual(stats["expirations"], 1)

    def test_generation_change_invalidates_entries(self):
        cache = TTLResponseCache()
        cache.sync_generation(10)
        cache.set("key", "old")
        cache.sync_generation(11)
        self.assertEqual(cache.get("key"), (False, None))
        self.assertEqual(cache.stats()["invalidations"], 1)

    def test_cache_failure_runs_normal_compute_path(self):
        cache = TTLResponseCache()
        with patch.object(cache, "get", side_effect=RuntimeError("cache unavailable")):
            self.assertEqual(cache.get_or_compute("key", lambda: {"ok": True}), {"ok": True})
        self.assertEqual(cache.stats()["errors"], 1)

    def test_generation_lookup_failure_disables_cache_for_request(self):
        with patch.object(server, "query", side_effect=RuntimeError("database unavailable")):
            self.assertIsNone(server.dashboard_data_generation())

    def test_concurrent_miss_runs_expensive_compute_once(self):
        cache = TTLResponseCache()
        started = threading.Event()
        release = threading.Event()
        calls = []

        def compute():
            calls.append(1)
            started.set()
            release.wait(1)
            return "value"

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(cache.get_or_compute, "same", compute)
            self.assertTrue(started.wait(1))
            second = executor.submit(cache.get_or_compute, "same", compute)
            time.sleep(0.02)
            release.set()
            self.assertEqual(first.result(), "value")
            self.assertEqual(second.result(), "value")
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.stats()["waits"], 1)

    def test_kpi_cache_uses_effective_scope_and_all_filters(self):
        response_cache = TTLResponseCache()
        scope_cache = TTLResponseCache()
        metadata_cache = TTLResponseCache()
        calls = []

        def positions(*args):
            return ["P1"] if args[5] == "Alice" else ["P2"]

        def calculate(*args, **kwargs):
            calls.append((args, kwargs))
            return {"employee": args[5], "metric": args[9]}

        with patch.object(server, "response_cache", response_cache), \
             patch.object(server, "scope_cache", scope_cache), \
             patch.object(server, "metadata_cache", metadata_cache), \
             patch.object(server, "dashboard_data_generation", return_value=7), \
             patch.object(server, "resolve_authorized_positions", side_effect=positions), \
             patch.object(server, "sales_summaries_ready", return_value=True), \
             patch.object(server, "_kpis_uncached", side_effect=calculate):
            first = server.kpis("HOD", "R", "Z", "S", "T", "Alice", "FMCG",
                                "Aug-2026", "2026-27", "tp")
            second = server.kpis("HOD", "R", "Z", "S", "T", "Alice", "FMCG",
                                 "Aug-2026", "2026-27", "tp")
            other = server.kpis("HOD", "R", "Z", "S", "T", "Bob", "FMCG",
                                "Aug-2026", "2026-27", "tp")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response_cache.stats()["hits"], 1)


if __name__ == "__main__":
    unittest.main()
