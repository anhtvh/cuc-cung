"""Sliding-window rate limiter per user_id (in-process, thread-safe).

Dùng cho /chat để chặn spam tốn credit.
max_calls=0 → disabled (contest default).
"""

import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, max_calls: int, window_seconds: int = 60) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        if self._max <= 0:
            return True
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        """Số lần còn lại trong window hiện tại."""
        if self._max <= 0:
            return 999
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.get(key, deque())
            used = sum(1 for t in bucket if t >= cutoff)
            return max(0, self._max - used)


_limiter: SlidingWindowRateLimiter | None = None
# Limiter thứ 2: cap số call /chat per user trong 1 "session window" (I-06, chống cháy credit).
# Tách khỏi _limiter (chặn burst/phút) — window dài hơn (mặc định 1h).
_session_limiter: SlidingWindowRateLimiter | None = None


def init_limiter(max_calls: int, window_seconds: int = 60) -> SlidingWindowRateLimiter:
    global _limiter
    _limiter = SlidingWindowRateLimiter(max_calls, window_seconds)
    return _limiter


def get_limiter() -> SlidingWindowRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowRateLimiter(max_calls=0)
    return _limiter


def init_session_limiter(max_calls: int, window_seconds: int = 3600) -> SlidingWindowRateLimiter:
    global _session_limiter
    _session_limiter = SlidingWindowRateLimiter(max_calls, window_seconds)
    return _session_limiter


def get_session_limiter() -> SlidingWindowRateLimiter:
    global _session_limiter
    if _session_limiter is None:
        _session_limiter = SlidingWindowRateLimiter(max_calls=0)
    return _session_limiter
