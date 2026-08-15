"""Suite registry — importing this package registers every suite."""

from evals.suites import (  # noqa: F401
    agents_deterministic,
    groundedness,
    retrieval,
    scribe_llm,
)
