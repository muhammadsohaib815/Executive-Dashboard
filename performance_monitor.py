"""Lightweight, data-free timing logs for dashboard HTTP and SQL work."""

import contextvars
import hashlib
import logging
import os
import sys
import threading
import time
from pathlib import Path


SLOW_QUERY_MS = 500.0
_endpoint = contextvars.ContextVar("dashboard_endpoint", default="background")
_known_api_paths = frozenset({
    "/api/meta", "/api/filters", "/api/employee-scope", "/api/kpis",
    "/api/ai-insights", "/api/ai-insights-legacy", "/api/cache-stats",
    "/api/db-pool-stats",
})
_logger = logging.getLogger("dashboard.performance")
_debug = os.getenv("DASHBOARD_PERF_DEBUG", os.getenv("DEBUG", "")).lower() in {
    "1", "true", "yes", "on"
}
_logger.setLevel(logging.DEBUG if _debug else logging.INFO)
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _logger.addHandler(_handler)
_logger.propagate = False


class DatabasePoolTimeout(TimeoutError):
    """Raised when a request cannot obtain a database slot within its deadline."""


class PoolMetrics:
    """Small, thread-safe pool counters; contains no SQL, credentials, or user data."""

    def __init__(self, maximum):
        self.maximum = maximum
        self._lock = threading.Lock()
        self.active = 0
        self.peak_active = 0
        self.acquisitions = 0
        self.exhaustions = 0
        self.connection_errors = 0
        self.total_wait_ms = 0.0
        self.max_wait_ms = 0.0

    def acquired(self, wait_ms):
        with self._lock:
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            self.acquisitions += 1
            self.total_wait_ms += wait_ms
            self.max_wait_ms = max(self.max_wait_ms, wait_ms)

    def released(self):
        with self._lock:
            self.active = max(0, self.active - 1)

    def exhausted(self, wait_ms):
        with self._lock:
            self.exhaustions += 1
            self.total_wait_ms += wait_ms
            self.max_wait_ms = max(self.max_wait_ms, wait_ms)

    def connection_error(self):
        with self._lock:
            self.connection_errors += 1

    def snapshot(self):
        with self._lock:
            attempts = self.acquisitions + self.exhaustions
            return {
                "maximum": self.maximum,
                "active": self.active,
                "available": max(0, self.maximum - self.active),
                "peak_active": self.peak_active,
                "acquisitions": self.acquisitions,
                "exhaustions": self.exhaustions,
                "connection_errors": self.connection_errors,
                "average_wait_ms": round(self.total_wait_ms / attempts, 2) if attempts else 0.0,
                "maximum_wait_ms": round(self.max_wait_ms, 2),
            }


def query_identifier(sql, frame=None):
    """Use a code location and SQL fingerprint; never include SQL or values in logs."""
    if frame is None:
        frame = sys._getframe(2)
    location = f"{Path(frame.f_code.co_filename).stem}.{frame.f_code.co_name}:{frame.f_lineno}"
    return f"{location}:{hashlib.blake2s(sql.encode('utf-8'), digest_size=4).hexdigest()}"


def log_query(query_id, query_ms, wait_ms, rows, failed=False, execute_ms=None, fetch_ms=None):
    level = logging.WARNING if query_ms > SLOW_QUERY_MS or failed else logging.INFO
    _logger.log(
        level,
        "event=sql endpoint=%s query_id=%s query_ms=%.2f connection_wait_ms=%.2f rows=%d slow=%s failed=%s",
        _endpoint.get(), query_id, query_ms, wait_ms, rows,
        str(query_ms > SLOW_QUERY_MS).lower(), str(failed).lower(),
    )
    if _logger.isEnabledFor(logging.DEBUG) and execute_ms is not None:
        _logger.debug(
            "event=sql_detail endpoint=%s query_id=%s execute_ms=%.2f fetch_ms=%.2f",
            _endpoint.get(), query_id, execute_ms, fetch_ms or 0.0,
        )


def run_query(pool, sql, params, query_id, slots=None, acquire_timeout_seconds=None,
              pool_metrics=None):
    """Execute and fetch with pool-wait, SQL, and row-count measurements."""
    wait_start = time.perf_counter()
    slot_acquired = False
    if slots is not None:
        slot_acquired = slots.acquire(timeout=acquire_timeout_seconds)
        if not slot_acquired:
            wait_ms = (time.perf_counter() - wait_start) * 1000
            if pool_metrics is not None:
                pool_metrics.exhausted(wait_ms)
            _logger.warning(
                "event=pool_exhausted endpoint=%s query_id=%s connection_wait_ms=%.2f",
                _endpoint.get(), query_id, wait_ms,
            )
            raise DatabasePoolTimeout("Database connection capacity is temporarily busy")
    try:
        conn = None
        wait_ms = 0.0
        query_ms = 0.0
        execute_ms = 0.0
        fetch_ms = 0.0
        rows = []
        columns = []
        failed = True
        try:
            try:
                conn = pool.getconn()
            except Exception:
                if pool_metrics is not None:
                    pool_metrics.connection_error()
                _logger.error(
                    "event=db_connection_error endpoint=%s query_id=%s",
                    _endpoint.get(), query_id,
                )
                raise
            wait_ms = (time.perf_counter() - wait_start) * 1000
            if pool_metrics is not None:
                pool_metrics.acquired(wait_ms)
            query_start = time.perf_counter()
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                execute_ms = (time.perf_counter() - query_start) * 1000
                rows = cursor.fetchall()
                fetch_ms = (time.perf_counter() - query_start) * 1000 - execute_ms
                query_ms = (time.perf_counter() - query_start) * 1000
                columns = [item[0] for item in cursor.description]
            failed = False
            return rows, columns
        finally:
            if conn is None:
                wait_ms = (time.perf_counter() - wait_start) * 1000
            elif failed and query_ms == 0.0:
                query_ms = (time.perf_counter() - query_start) * 1000
            log_query(query_id, query_ms, wait_ms, len(rows), failed, execute_ms, fetch_ms)
            if conn is not None:
                try:
                    conn.rollback()
                finally:
                    try:
                        pool.putconn(conn)
                    except Exception:
                        if pool_metrics is not None:
                            pool_metrics.connection_error()
                        _logger.error(
                            "event=db_connection_return_error endpoint=%s query_id=%s",
                            _endpoint.get(), query_id,
                        )
                        raise
                    finally:
                        if pool_metrics is not None:
                            pool_metrics.released()
    finally:
        if slots is not None and slot_acquired:
            slots.release()


class EndpointTimingMiddleware:
    """ASGI timing includes response construction and final body transmission."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        endpoint = path if path in _known_api_paths else "other"
        token = _endpoint.set(endpoint)
        start = time.perf_counter()
        status = 500

        async def timed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if endpoint != "other":
                _logger.info("event=http endpoint=%s status=%d response_ms=%.2f", endpoint, status, elapsed_ms)
            _endpoint.reset(token)
