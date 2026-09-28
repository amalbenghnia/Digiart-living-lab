"""Simple in-memory TTL cache with manual invalidation support.

Each decorated method gets its own cache dict (closure).
Call  method.cache_clear()  on any instance to flush all entries.
"""
import time
from functools import wraps


def ttl_cache(ttl_seconds: int):
    """TTL cache decorator for instance methods. Supports .cache_clear()."""
    def decorator(func):
        cache: dict = {}

        @wraps(func)
        def wrapper(self, *args, **kwargs):
            key = (id(self), args, tuple(sorted(kwargs.items())))
            now = time.time()
            if key in cache:
                result, ts = cache[key]
                if now - ts < ttl_seconds:
                    return result
            result = func(self, *args, **kwargs)
            cache[key] = (result, now)
            return result

        def cache_clear():
            cache.clear()

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        return wrapper
    return decorator
