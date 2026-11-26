"""In-memory failure throttle for the sign-in endpoints.

Counts failed attempts per key (the sender's address, and the email being
tried) in a sliding window and refuses further tries once a key passes its
limit, so a password can't be guessed by brute force and the endpoint can't be
hammered to probe who has an account. Production runs one backend process, so
process memory is the right store; a restart forgets the counts, which only
ever errs towards letting a real person back in.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class Throttle:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def check(self, *keys: str | None) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                if key and len(self._live(key, now)) >= self.limit:
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "Too many attempts — wait a few minutes and try again",
                    )

    def fail(self, *keys: str | None) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                if key:
                    self._live(key, now).append(now)
            if len(self._hits) > 50_000:  # keep memory bounded under a flood
                for key in [k for k, v in self._hits.items() if not v]:
                    del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Sign-in: 10 wrong passwords per address or per account in 15 minutes.
login_failures = Throttle(limit=10, window_seconds=15 * 60)
# Unauthenticated mail-sending / account forms: 20 per address per hour.
account_forms = Throttle(limit=20, window_seconds=60 * 60)
