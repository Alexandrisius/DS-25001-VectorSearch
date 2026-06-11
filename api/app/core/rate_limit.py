"""Rate-limit для попыток входа в админку (in-memory)."""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List

from app.config import get_settings


class LoginRateLimiter:
    """Простой in-memory rate limiter.

    Защищает от брутфорса: после N неудачных попыток входа — IP блокируется на M минут.
    """

    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 5) -> None:
        self.attempts: Dict[str, List[float]] = {}
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_minutes * 60
        self._lock = asyncio.Lock()

    async def is_blocked(self, ip: str) -> bool:
        async with self._lock:
            return self._is_blocked_unlocked(ip)

    def _is_blocked_unlocked(self, ip: str) -> bool:
        if ip not in self.attempts:
            return False
        now = time.time()
        self.attempts[ip] = [t for t in self.attempts[ip] if now - t < self.lockout_seconds]
        return len(self.attempts[ip]) >= self.max_attempts

    async def record_attempt(self, ip: str) -> None:
        async with self._lock:
            self.attempts.setdefault(ip, []).append(time.time())

    async def clear(self, ip: str) -> None:
        async with self._lock:
            self.attempts.pop(ip, None)

    def get_remaining_time(self, ip: str) -> int:
        if ip not in self.attempts or not self.attempts[ip]:
            return 0
        oldest = min(self.attempts[ip])
        return max(0, int(self.lockout_seconds - (time.time() - oldest)))


# Singleton
_rate_limiter: LoginRateLimiter | None = None


def get_login_rate_limiter() -> LoginRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        s = get_settings()
        _rate_limiter = LoginRateLimiter(s.login_max_attempts, s.login_lockout_minutes)
    return _rate_limiter


__all__ = ["LoginRateLimiter", "get_login_rate_limiter"]
