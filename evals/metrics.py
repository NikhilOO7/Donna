"""Shared metric computations for the eval harness."""

from typing import Any, Dict, List, Tuple


def classification_metrics(
    results: List[Tuple[bool, bool]],
) -> Dict[str, float]:
    """Precision / recall / F1 / accuracy from (expected, predicted) pairs."""
    tp = sum(1 for e, p in results if e and p)
    fp = sum(1 for e, p in results if not e and p)
    fn = sum(1 for e, p in results if e and not p)
    tn = sum(1 for e, p in results if not e and not p)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(results) if results else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }


def exact_match_rate(results: List[Tuple[Any, Any]]) -> float:
    """Fraction of (expected, predicted) pairs that match exactly."""
    if not results:
        return 0.0
    return round(sum(1 for e, p in results if e == p) / len(results), 4)
