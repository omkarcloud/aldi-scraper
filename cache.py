"""In-process response cache: cached_call(namespace, params, fn, ttl) serves
fn(**params) from memory until `ttl` (a timedelta) runs out. Keeps repeat
lookups of the same product, category tree or store off Aldi while the server
runs. A function may return DontCache(result) to skip storing one answer."""
import json
import threading
import time

_store = {}
_lock = threading.Lock()
MAX_ENTRIES = 2000


class DontCache:
    """Wrap a result to return it without storing it."""

    def __init__(self, data):
        self.data = data


def cached_call(namespace, data, fn, ttl, cache=True):
    seconds = ttl.total_seconds() if hasattr(ttl, "total_seconds") else (ttl or 0)
    key = namespace + ":" + json.dumps(data, sort_keys=True, default=str)
    now = time.monotonic()
    if cache and seconds:
        with _lock:
            hit = _store.get(key)
            if hit and hit[0] > now:
                return hit[1]
    result = fn(**data)
    if isinstance(result, DontCache):
        return result.data
    if cache and seconds:
        with _lock:
            if len(_store) >= MAX_ENTRIES:
                _store.clear()
            _store[key] = (now + seconds, result)
    return result
