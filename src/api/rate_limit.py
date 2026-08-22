"""In-memory abuse guards for /ws/call: caps concurrent sessions and per-IP
connection rate, independent of auth -- a valid API key doesn't stop a buggy
client from draining the LLM quota or pegging the CPU. Single-process only
(fine for this project's scope); a real multi-worker deployment would need
a shared store (Redis etc.) instead of these module-level dicts."""

import time
from collections import defaultdict

from src.config import settings

_active_calls = 0
_connect_times_by_ip: dict[str, list[float]] = defaultdict(list)


class RateLimitExceeded(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def check_and_register(client_ip: str) -> None:
    """Raises RateLimitExceeded if this connection should be refused.
    On success, call release() exactly once when the connection ends."""
    global _active_calls

    if _active_calls >= settings.max_concurrent_calls:
        raise RateLimitExceeded(
            f"max_concurrent_calls ({settings.max_concurrent_calls}) reached"
        )

    now = time.monotonic()
    recent = [t for t in _connect_times_by_ip[client_ip] if now - t < 60]
    if len(recent) >= settings.max_calls_per_ip_per_minute:
        raise RateLimitExceeded(
            f"max_calls_per_ip_per_minute ({settings.max_calls_per_ip_per_minute}) "
            f"reached for {client_ip}"
        )

    recent.append(now)
    _connect_times_by_ip[client_ip] = recent
    _active_calls += 1


def release() -> None:
    global _active_calls
    _active_calls = max(0, _active_calls - 1)


def reset_for_tests() -> None:
    """Test-only: clear all state between tests."""
    global _active_calls
    _active_calls = 0
    _connect_times_by_ip.clear()
