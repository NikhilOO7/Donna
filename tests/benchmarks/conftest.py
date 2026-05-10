"""Shared fixtures and utilities for performance benchmarks."""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import List


@dataclass
class BenchmarkResult:
    name: str
    durations_ms: List[float] = field(default_factory=list)

    @property
    def mean_ms(self) -> float:
        return (
            sum(self.durations_ms) / len(self.durations_ms) if self.durations_ms else 0
        )

    @property
    def p95_ms(self) -> float:
        if not self.durations_ms:
            return 0
        sorted_d = sorted(self.durations_ms)
        idx = int(len(sorted_d) * 0.95)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    def __str__(self) -> str:
        return (
            f"{self.name}: mean={self.mean_ms:.1f}ms  "
            f"p95={self.p95_ms:.1f}ms  "
            f"n={len(self.durations_ms)}"
        )


@contextmanager
def timer(result: BenchmarkResult):
    """Context manager that records elapsed time into a BenchmarkResult."""
    start = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - start) * 1000
    result.durations_ms.append(elapsed_ms)
