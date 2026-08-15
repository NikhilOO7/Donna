"""
Resilience patterns for external API calls.

Combines retry with exponential backoff, circuit breaker, timeout,
and Prometheus instrumentation into a single reusable decorator.
"""

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from apps.api.core.metrics import EXTERNAL_API_CALLS_TOTAL, EXTERNAL_API_DURATION

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Simple circuit breaker state machine
# ---------------------------------------------------------------------------
@dataclass
class CircuitBreaker:
    """Per-service circuit breaker.

    States:
        CLOSED   - normal operation, failures counted
        OPEN     - calls rejected immediately, waiting for recovery_timeout
        HALF_OPEN - one trial call allowed; success closes, failure re-opens
    """

    service_name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0

    _failure_count: int = field(default=0, repr=False)
    _state: str = field(default="CLOSED", repr=False)
    _last_failure_time: float = field(default=0.0, repr=False)

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = "HALF_OPEN"
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = "OPEN"
            logger.warning(
                f"Circuit breaker OPEN for {self.service_name} "
                f"after {self._failure_count} failures"
            )

    def allow_request(self) -> bool:
        state = self.state
        if state == "CLOSED":
            return True
        if state == "HALF_OPEN":
            return True  # allow one probe
        return False  # OPEN


# Global registry so health endpoint can report states
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(service_name: str, **kwargs) -> CircuitBreaker:
    if service_name not in _breakers:
        _breakers[service_name] = CircuitBreaker(service_name=service_name, **kwargs)
    return _breakers[service_name]


def get_all_breaker_states() -> dict[str, str]:
    """Return {service_name: state} for all registered breakers."""
    return {name: cb.state for name, cb in _breakers.items()}


# ---------------------------------------------------------------------------
# Cross-replica breaker state (Redis-backed, best-effort)
# ---------------------------------------------------------------------------
# The local breaker above is per-process. With N replicas, each one has to
# independently rediscover that a provider is down, so the fleet sends up to
# N x failure_threshold doomed requests before all breakers open — and a
# recovering provider gets probed by every replica at once.
#
# Sharing the *trip decision* through Redis fixes both: the first replica to
# open the circuit opens it for everyone, and the half-open probe is claimed
# by a single replica via SET NX. Entirely best-effort — if Redis is
# unavailable every call falls back to the local breaker and behaviour is
# exactly as before.

_CB_PREFIX = "cb:"


async def _cb_redis():
    try:
        from apps.api.core.connections import get_redis_client

        return await get_redis_client()
    except Exception:
        return None


async def shared_is_open(service_name: str) -> bool:
    """True if any replica has tripped this circuit and it hasn't recovered."""
    r = await _cb_redis()
    if r is None:
        return False
    try:
        return bool(await r.get(f"{_CB_PREFIX}{service_name}:open"))
    except Exception:
        return False


async def shared_claim_probe(service_name: str, recovery_timeout: float) -> bool:
    """Claim the single half-open trial call across the fleet.

    Returns True for exactly one caller per recovery window; everyone else
    keeps failing fast instead of stampeding a recovering provider.
    """
    r = await _cb_redis()
    if r is None:
        return True  # no Redis: local breaker semantics, every replica probes
    try:
        ok = await r.set(
            f"{_CB_PREFIX}{service_name}:probe",
            "1",
            nx=True,
            ex=max(1, int(recovery_timeout)),
        )
        return bool(ok)
    except Exception:
        return True


async def shared_record_failure(
    service_name: str, threshold: int, recovery_timeout: float
) -> None:
    """Count a failure fleet-wide and trip the shared circuit at the threshold."""
    r = await _cb_redis()
    if r is None:
        return
    try:
        key = f"{_CB_PREFIX}{service_name}:failures"
        count = await r.incr(key)
        if count == 1:
            # Window the counter so old failures don't accumulate forever.
            await r.expire(key, max(1, int(recovery_timeout * 2)))
        if count >= threshold:
            await r.set(
                f"{_CB_PREFIX}{service_name}:open",
                "1",
                ex=max(1, int(recovery_timeout)),
            )
            logger.warning(
                f"Circuit breaker OPEN (fleet-wide) for {service_name} "
                f"after {count} failures across all replicas"
            )
    except Exception:
        pass


async def shared_record_success(service_name: str) -> None:
    """Clear shared failure state — the provider answered."""
    r = await _cb_redis()
    if r is None:
        return
    try:
        await r.delete(
            f"{_CB_PREFIX}{service_name}:failures",
            f"{_CB_PREFIX}{service_name}:open",
            f"{_CB_PREFIX}{service_name}:probe",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Resilient call decorator
# ---------------------------------------------------------------------------
class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and rejects a call."""


# How much longer a fallback backend is allowed to take. The per-agent
# timeouts are latency budgets for gpt-4o-mini; a 20B reasoning model on a
# free tier is several times slower, and a cold start slower still. Without
# this, every live-meeting agent times out the moment failover engages.
_LOCAL_TIMEOUT_MULTIPLIER = 4.0
_CLOUD_TIMEOUT_MULTIPLIER = 5.0
# Floor for the tightest budgets: 10s x 4 is still not enough for a first
# token from a large model.
_FALLBACK_MIN_TIMEOUT_S = 60.0


def _effective_target(timeout_seconds: float) -> tuple[str, float]:
    """Resolve the backend an "openai"-declared call will actually hit.

    Returns ``(breaker_key, timeout_budget)``. Falls back to the declared
    values if the provider layer is unavailable for any reason — this is on
    the hot path for every agent call and must never be the thing that breaks.
    """
    try:
        from apps.api.core import llm_provider

        provider = llm_provider.active_provider()
        if provider.name == "openai":
            return "openai", timeout_seconds
        multiplier = (
            _CLOUD_TIMEOUT_MULTIPLIER
            if provider.name == "ollama-cloud"
            else _LOCAL_TIMEOUT_MULTIPLIER
        )
        return provider.name, max(timeout_seconds * multiplier, _FALLBACK_MIN_TIMEOUT_S)
    except Exception:
        return "openai", timeout_seconds


def resilient_call(
    service_name: str,
    max_retries: int = 3,
    timeout_seconds: float = 30.0,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
):
    """Decorator combining retry + circuit breaker + timeout + Prometheus metrics.

    Usage::

        @resilient_call("openai")
        async def call_openai(prompt: str) -> str:
            ...
    """

    def decorator(fn: F) -> F:
        breaker = get_breaker(
            service_name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )

        # Tenacity retry wrapper (retries on transient errors, not on CircuitOpenError)
        retrying = retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            # Resolve which backend this call will actually reach. Agents
            # declare service_name="openai", but when the provider layer has
            # failed over, the request goes to Ollama instead — and treating
            # that as "openai" breaks in two ways:
            #
            #   1. A slow Ollama response trips the OpenAI breaker, which then
            #      rejects calls that would have gone to Ollama anyway. The
            #      breaker ends up protecting a service nobody is calling and
            #      blocking the one that still works.
            #   2. The timeouts here are latency budgets tuned for gpt-4o-mini.
            #      A 20B reasoning model on a free tier does not answer in 10s,
            #      so every live-meeting agent would time out permanently.
            #
            # So the breaker is keyed by the real backend, and the budget is
            # scaled for it.
            svc = service_name
            budget = timeout_seconds
            if service_name == "openai":
                svc, budget = _effective_target(timeout_seconds)

            local_breaker = (
                breaker
                if svc == service_name
                else get_breaker(
                    svc,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                )
            )

            # Local breaker first (free, no I/O), then the shared one so a
            # circuit any replica tripped is honoured here too.
            allowed = local_breaker.allow_request()
            if allowed and await shared_is_open(svc):
                # Another replica has tripped it. Exactly one caller per
                # recovery window is allowed through as the trial probe.
                allowed = await shared_claim_probe(svc, recovery_timeout)

            if not allowed:
                EXTERNAL_API_CALLS_TOTAL.labels(
                    service=svc, status="circuit_open"
                ).inc()
                raise CircuitOpenError(
                    f"Circuit breaker OPEN for {svc}. "
                    f"Retrying in {local_breaker.recovery_timeout}s."
                )

            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    retrying(fn)(*args, **kwargs),
                    timeout=budget,
                )
                duration = time.monotonic() - start
                local_breaker.record_success()
                await shared_record_success(svc)
                EXTERNAL_API_CALLS_TOTAL.labels(service=svc, status="success").inc()
                EXTERNAL_API_DURATION.labels(service=svc).observe(duration)
                return result

            except asyncio.TimeoutError:
                local_breaker.record_failure()
                await shared_record_failure(svc, failure_threshold, recovery_timeout)
                EXTERNAL_API_CALLS_TOTAL.labels(service=svc, status="timeout").inc()
                logger.error(f"{svc} call timed out after {budget}s")
                raise

            except Exception as exc:
                duration = time.monotonic() - start
                local_breaker.record_failure()
                await shared_record_failure(svc, failure_threshold, recovery_timeout)
                EXTERNAL_API_CALLS_TOTAL.labels(service=svc, status="error").inc()
                EXTERNAL_API_DURATION.labels(service=svc).observe(duration)
                logger.error(f"{svc} call failed: {exc}")
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
