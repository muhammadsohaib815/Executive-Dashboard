"""Monitoring tests use fake database objects and never connect to PostgreSQL."""

import logging
import threading
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import performance_monitor as monitor


class _Cursor:
    description = [("value",)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return [(1,), (2,)]


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()
        self.rolled_back = False

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rolled_back = True


class _Pool:
    def __init__(self):
        self.connection = _Connection()
        self.returned = False

    def getconn(self):
        return self.connection

    def putconn(self, connection):
        self.returned = connection is self.connection


class _RecordHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class PerformanceMonitorTests(unittest.TestCase):
    def setUp(self):
        self.handler = _RecordHandler()
        monitor._logger.addHandler(self.handler)
        self.previous_level = monitor._logger.level
        monitor._logger.setLevel(logging.DEBUG)

    def tearDown(self):
        monitor._logger.removeHandler(self.handler)
        monitor._logger.setLevel(self.previous_level)

    def test_query_results_and_redacted_logs(self):
        pool = _Pool()
        rows, columns = monitor.run_query(
            pool, "SELECT value FROM private WHERE customer = %s", ["Sensitive Customer"], "test.private"
        )
        self.assertEqual((rows, columns), ([(1,), (2,)], ["value"]))
        self.assertTrue(pool.connection.rolled_back)
        self.assertTrue(pool.returned)
        messages = "\n".join(record.getMessage() for record in self.handler.records)
        self.assertIn("query_id=test.private", messages)
        self.assertIn("rows=2", messages)
        self.assertIn("connection_wait_ms=", messages)
        self.assertNotIn("Sensitive Customer", messages)
        self.assertNotIn("SELECT", messages)

    def test_slow_query_uses_warning(self):
        monitor.log_query("test.slow", 500.01, 2.0, 3)
        self.assertEqual(self.handler.records[-1].levelno, logging.WARNING)
        self.assertIn("slow=true", self.handler.records[-1].getMessage())

    def test_failed_query_preserves_error_and_hides_values(self):
        pool = _Pool()

        def fail(sql, params):
            raise ValueError("Sensitive Customer")

        pool.connection.cursor_instance.execute = fail
        with self.assertRaisesRegex(ValueError, "Sensitive Customer"):
            monitor.run_query(pool, "SELECT private_value", ["Sensitive Customer"], "test.failure")
        self.assertTrue(pool.connection.rolled_back)
        self.assertTrue(pool.returned)
        message = next(r.getMessage() for r in self.handler.records if "event=sql " in r.getMessage())
        self.assertIn("failed=true", message)
        self.assertNotIn("Sensitive Customer", message)

    def test_endpoint_response_is_unchanged_and_path_is_safe(self):
        app = FastAPI()
        app.add_middleware(monitor.EndpointTimingMiddleware)

        @app.get("/api/kpis")
        def kpis():
            monitor.log_query("test.endpoint", 1.0, 0.5, 1)
            return {"value": 42}

        with TestClient(app) as client:
            response = client.get("/api/kpis?token=secret-token")
        self.assertEqual(response.json(), {"value": 42})
        messages = "\n".join(record.getMessage() for record in self.handler.records)
        self.assertIn("endpoint=/api/kpis", messages)
        self.assertIn("response_ms=", messages)
        self.assertNotIn("secret-token", messages)

    def test_pool_timeout_is_bounded_and_counted(self):
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        metrics = monitor.PoolMetrics(1)
        try:
            with self.assertRaises(monitor.DatabasePoolTimeout):
                monitor.run_query(
                    _Pool(), "SELECT 1", [], "test.pool_timeout", slots,
                    acquire_timeout_seconds=0.001, pool_metrics=metrics,
                )
        finally:
            slots.release()
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["exhaustions"], 1)
        self.assertEqual(snapshot["active"], 0)

    def test_pool_metrics_release_after_success(self):
        metrics = monitor.PoolMetrics(2)
        slots = threading.BoundedSemaphore(2)
        monitor.run_query(
            _Pool(), "SELECT 1", [], "test.pool_success", slots,
            acquire_timeout_seconds=1, pool_metrics=metrics,
        )
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["acquisitions"], 1)
        self.assertEqual(snapshot["peak_active"], 1)
        self.assertEqual(snapshot["active"], 0)


if __name__ == "__main__":
    unittest.main()
