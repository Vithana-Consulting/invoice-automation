"""Rotating API-key pool with per-key cooldown — failover for all integrations.

Each integration (LLM parser, LlamaParse, Zoho/QuickBooks OAuth) can be given a
*pool* of credentials instead of a single one. When a key hits a rate limit
(HTTP 429) or any other transient failure, the pool parks that key in a short
cooldown window and the next healthy key is used instead. After the cooldown
elapses the key re-enters the rotation, so a momentary 429 never permanently
shrinks the pool.

Design goals:
  - Backward compatible: a pool of one key behaves exactly as a single key.
  - Zero config: a single key string still "just works".
  - Process-wide state: cooldowns are remembered across calls within a process
    (the pool registry is a module-level singleton keyed by integration name).
  - Thread-safe: guarded by a lock; safe under FastAPI's threadpool.

Usage:
    pool = get_key_pool("llm", settings.LLM_API_KEY)
    result = run_with_rotation(pool, lambda key: call_provider(key, prompt))
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

logger = logging.getLogger(__name__)

# Default time a key is parked after a failure before it's eligible again.
DEFAULT_COOLDOWN_SECONDS = 60.0

# Separators allowed between keys in a single config string.
_SPLIT_RE = re.compile(r"[,;\n\r]+")


class KeyExhaustedError(Exception):
    """Every key in the pool is currently in cooldown or the pool is empty."""


def parse_keys(raw: str) -> List[str]:
    """Split a config value into an ordered, de-duplicated list of keys.

    Keys may be separated by commas, semicolons, or newlines so a single config
    field (env var or runtime override) can hold a whole pool. Whitespace is
    trimmed; blanks and duplicates are dropped while preserving order.

    A normal single key (no separators) yields a one-element list — fully
    backward compatible.
    """
    if not raw:
        return []
    seen: set[str] = set()
    keys: List[str] = []
    for part in _SPLIT_RE.split(raw):
        k = part.strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def mask_key(key: str) -> str:
    """Mask a secret for safe logging / API responses."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


@dataclass
class _KeyState:
    key: str
    cooldown_until: float = 0.0  # monotonic timestamp; 0 = healthy
    failures: int = 0
    last_error: str = ""


class KeyPool:
    """A rotating pool of credentials with per-key cooldown.

    The "key" can be any opaque string — an API key, or an index/handle into a
    list of OAuth credential sets. The pool itself is credential-agnostic.
    """

    def __init__(self, name: str, keys: Iterable[str],
                 cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS):
        self.name = name
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._lock = threading.Lock()
        self._states: List[_KeyState] = [_KeyState(k) for k in keys]
        self._idx = 0

    def __len__(self) -> int:
        return len(self._states)

    def key_list(self) -> List[str]:
        return [s.key for s in self._states]

    def acquire(self) -> str:
        """Return the current active key, skipping any in cooldown.

        Raises KeyExhaustedError if the pool is empty or every key is cooling
        down (the message reports how long until the soonest key recovers).
        """
        with self._lock:
            n = len(self._states)
            if n == 0:
                raise KeyExhaustedError(f"{self.name}: no keys configured")
            now = time.monotonic()
            for offset in range(n):
                pos = (self._idx + offset) % n
                st = self._states[pos]
                if st.cooldown_until <= now:
                    self._idx = pos
                    return st.key
            soonest = min(self._states, key=lambda s: s.cooldown_until)
            wait = max(0.0, soonest.cooldown_until - now)
            raise KeyExhaustedError(
                f"{self.name}: all {n} key(s) cooling down; "
                f"next available in ~{wait:.0f}s"
            )

    def report_failure(self, key: str, error: str = "",
                       cooldown: Optional[float] = None) -> None:
        """Park a key after a failure and advance the rotation past it."""
        with self._lock:
            for i, st in enumerate(self._states):
                if st.key == key:
                    st.failures += 1
                    st.last_error = error[:300]
                    st.cooldown_until = time.monotonic() + (
                        self._cooldown if cooldown is None else max(0.0, cooldown)
                    )
                    self._idx = (i + 1) % len(self._states)
                    logger.warning(
                        "KeyPool[%s]: parked key %s (#%d/%d) for %.0fs — %s",
                        self.name, mask_key(key), i + 1, len(self._states),
                        self._cooldown if cooldown is None else cooldown, error,
                    )
                    return

    def report_success(self, key: str) -> None:
        """Clear a key's failure/cooldown state after a successful call."""
        with self._lock:
            for st in self._states:
                if st.key == key:
                    if st.failures or st.cooldown_until:
                        logger.info("KeyPool[%s]: key %s recovered",
                                    self.name, mask_key(st.key))
                    st.failures = 0
                    st.cooldown_until = 0.0
                    return

    def status(self) -> List[dict]:
        """Masked, JSON-safe snapshot of pool health for the admin dashboard."""
        with self._lock:
            now = time.monotonic()
            return [
                {
                    "index": i + 1,
                    "key": mask_key(st.key),
                    "healthy": st.cooldown_until <= now,
                    "failures": st.failures,
                    "cooldown_remaining_s": round(max(0.0, st.cooldown_until - now), 1),
                    "last_error": st.last_error,
                }
                for i, st in enumerate(self._states)
            ]


# ── Process-wide registry ───────────────────────────────────────────────────
# Pools are cached per integration name so cooldown state persists across calls.
# If the configured keys change at runtime (admin override), the pool is rebuilt.

_REGISTRY: dict[str, KeyPool] = {}
_REGISTRY_LOCK = threading.Lock()


def get_key_pool(name: str, raw_keys: str,
                 cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS) -> KeyPool:
    """Get (or build) the named key pool from a raw config string.

    The same `name` always returns the same pool instance (so cooldowns are
    remembered), unless the configured key set has changed — in which case the
    pool is rebuilt with the new keys.
    """
    keys = parse_keys(raw_keys)
    with _REGISTRY_LOCK:
        existing = _REGISTRY.get(name)
        if existing is None or existing.key_list() != keys:
            _REGISTRY[name] = KeyPool(name, keys, cooldown_seconds)
            logger.info("KeyPool[%s]: initialised with %d key(s)", name, len(keys))
        return _REGISTRY[name]


def all_pool_status() -> dict:
    """Masked health snapshot of every registered pool (for admin endpoint)."""
    with _REGISTRY_LOCK:
        pools = list(_REGISTRY.values())
    return {p.name: p.status() for p in pools}


def is_fatal_error(exc: Exception) -> bool:
    """Return True for errors that rotating keys will NOT fix.

    A 400/404/422 means the *request* is bad (malformed payload, missing
    field) — every key would fail identically, so we should not waste the pool
    rotating. Everything else (429, 401, 403, 5xx, timeouts, connection errors)
    is treated as key/transport-related and IS worth rotating for.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
    if status in (400, 404, 422):
        return True
    return False


def run_with_rotation(
    pool: KeyPool,
    fn: Callable[[str], object],
    max_attempts: Optional[int] = None,
    is_fatal: Callable[[Exception], bool] = is_fatal_error,
) -> object:
    """Run ``fn(key)`` against the pool, rotating keys on failure.

    ``fn`` receives the active key and returns a result. If it raises, the key
    is parked (cooldown) and the next healthy key is tried. Up to
    ``max_attempts`` distinct attempts are made (defaults to the pool size, min
    1). The last exception is re-raised once every attempt is exhausted.

    ``is_fatal(exc)`` short-circuits rotation: if it returns True the exception
    is re-raised immediately without parking the key (rotating won't help).
    """
    if max_attempts is None:
        max_attempts = max(1, len(pool))
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            key = pool.acquire()
        except KeyExhaustedError:
            if last_exc is not None:
                raise last_exc
            raise
        try:
            result = fn(key)
            pool.report_success(key)
            return result
        except Exception as exc:  # noqa: BLE001 — deliberate broad catch for failover
            if is_fatal(exc):
                raise
            last_exc = exc
            pool.report_failure(key, f"{type(exc).__name__}: {exc}")
            logger.warning(
                "KeyPool[%s]: attempt %d/%d failed, rotating key — %s",
                pool.name, attempt, max_attempts, exc,
            )
    if last_exc is not None:
        raise last_exc
    raise KeyExhaustedError(f"{pool.name}: no attempts made")
