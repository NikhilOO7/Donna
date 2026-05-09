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
from typing import Callable, TypeVar, Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
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
# Resilient call decorator
# ---------------------------------------------------------------------------
class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and rejects a call."""


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
            if not breaker.allow_request():
                EXTERNAL_API_CALLS_TOTAL.labels(service=service_name, status="circuit_open").inc()
                raise CircuitOpenError(
                    f"Circuit breaker OPEN for {service_name}. "
                    f"Retrying in {breaker.recovery_timeout}s."
                )

            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    retrying(fn)(*args, **kwargs),
                    timeout=timeout_seconds,
                )
                duration = time.monotonic() - start
                breaker.record_success()
                EXTERNAL_API_CALLS_TOTAL.labels(service=service_name, status="success").inc()
                EXTERNAL_API_DURATION.labels(service=service_name).observe(duration)
                return result

            except asyncio.TimeoutError:
                breaker.record_failure()
                EXTERNAL_API_CALLS_TOTAL.labels(service=service_name, status="timeout").inc()
                logger.error(f"{service_name} call timed out after {timeout_seconds}s")
                raise

            except Exception as exc:
                duration = time.monotonic() - start
                breaker.record_failure()
                EXTERNAL_API_CALLS_TOTAL.labels(service=service_name, status="error").inc()
                EXTERNAL_API_DURATION.labels(service=service_name).observe(duration)
                logger.error(f"{service_name} call failed: {exc}")
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
