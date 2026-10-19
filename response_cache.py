"""Bounded, thread-safe TTL cache for expensive read-only API responses."""

from collections import OrderedDict
import logging
import threading
import time


_logger = logging.getLogger("dashboard.cache")
if not _logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _logger.addHandler(handler)
_logger.propagate = False


class TTLResponseCache:
    """Small in-process LRU cache with TTL, generation invalidation, and metrics."""

    def __init__(self, ttl_seconds=600, max_entries=128, enabled=True, clock=None):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.enabled = enabled
        self._clock = clock or time.monotonic
        self._items = OrderedDict()
        self._inflight = {}
        self._lock = threading.RLock()
        self._generation = None
        self._stats = {
            "hits": 0, "misses": 0, "sets": 0, "evictions": 0,
            "expirations": 0, "invalidations": 0, "errors": 0, "waits": 0,
        }

    def sync_generation(self, generation):
        if not self.enabled or generation is None:
            return
        with self._lock:
            if self._generation is None:
                self._generation = generation
            elif self._generation != generation:
                self._items.clear()
                self._generation = generation
                self._stats["invalidations"] += 1
                _logger.info("event=cache_invalidate reason=data_generation")

    def get(self, key):
        if not self.enabled:
            return False, None
        now = self._clock()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self._stats["misses"] += 1
                return False, None
            expires_at, value = item
            if expires_at <= now:
                del self._items[key]
                self._stats["misses"] += 1
                self._stats["expirations"] += 1
                return False, None
            self._items.move_to_end(key)
            self._stats["hits"] += 1
            return True, value

    def set(self, key, value):
        if not self.enabled:
            return
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_seconds, value)
            self._items.move_to_end(key)
            self._stats["sets"] += 1
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
                self._stats["evictions"] += 1

    def get_or_compute(self, key, compute):
        """Return a cached value; any cache failure executes the normal query path."""
        try:
            found, value = self.get(key)
            if found:
                _logger.info("event=cache_request result=hit")
                return value
        except Exception:
            with self._lock:
                self._stats["errors"] += 1
            return compute()
        with self._lock:
            event = self._inflight.get(key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[key] = event
            else:
                self._stats["waits"] += 1
        if not owner:
            event.wait()
            try:
                found, value = self.get(key)
                if found:
                    _logger.info("event=cache_request result=hit_after_wait")
                    return value
            except Exception:
                with self._lock:
                    self._stats["errors"] += 1
            return self.get_or_compute(key, compute)
        _logger.info("event=cache_request result=miss")
        try:
            value = compute()
            try:
                self.set(key, value)
            except Exception:
                with self._lock:
                    self._stats["errors"] += 1
            return value
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                event.set()

    def clear(self):
        with self._lock:
            self._items.clear()
            self._stats["invalidations"] += 1

    def stats(self):
        with self._lock:
            values = dict(self._stats)
            values["entries"] = len(self._items)
            values["max_entries"] = self.max_entries
            values["ttl_seconds"] = self.ttl_seconds
            values["enabled"] = self.enabled
            values["generation"] = self._generation
        attempts = values["hits"] + values["misses"]
        values["hit_rate_pct"] = round(values["hits"] / attempts * 100, 1) if attempts else 0.0
        values["miss_rate_pct"] = round(values["misses"] / attempts * 100, 1) if attempts else 0.0
        return values
