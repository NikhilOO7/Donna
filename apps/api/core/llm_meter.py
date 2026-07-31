"""
Per-meeting LLM cost metering.

The founder-critical number: what does a meeting actually cost to run?
Every instrumented LLM call records its token usage into a Redis hash per
meeting; totals are exposed via ``GET /api/v1/meetings/{id}/cost``.

Best-effort by design — metering must never break a pipeline.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# USD per 1M tokens (input, output) — update alongside model changes.
_PRICES: Dict[str, tuple] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo-preview": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "text-embedding-3-small": (0.02, 0.0),
}

_TTL_SECONDS = 60 * 60 * 24 * 30  # keep per-meeting cost for 30 days


def _key(meeting_id: str) -> str:
    return f"llmcost:{meeting_id}"


async def record(
    meeting_id: Optional[str],
    agent: str,
    model: str,
    usage: Any,
) -> None:
    """Record one LLM call's usage. ``usage`` is the OpenAI usage object."""
    if not meeting_id or usage is None:
        return
    try:
        from apps.api.core.connections import get_redis_client

        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)

        redis = await get_redis_client()
        key = _key(str(meeting_id))
        pipe = redis.pipeline()
        pipe.hincrby(key, "prompt_tokens", prompt)
        pipe.hincrby(key, "completion_tokens", completion)
        pipe.hincrby(key, "calls", 1)
        pipe.hincrby(key, f"agent:{agent}:tokens", prompt + completion)
        # Micro-USD to keep integer math in Redis
        in_price, out_price = _PRICES.get(model, (2.50, 10.00))
        micro_usd = int(prompt * in_price + completion * out_price)  # per 1M → µ$
        pipe.hincrby(key, "micro_usd", micro_usd)
        pipe.expire(key, _TTL_SECONDS)
        await pipe.execute()
    except Exception:
        pass  # metering is never allowed to break the caller


async def get_cost(meeting_id: str) -> Dict[str, Any]:
    """Aggregate cost for a meeting. Zeros when nothing recorded/Redis down."""
    try:
        from apps.api.core.connections import get_redis_client

        redis = await get_redis_client()
        raw = await redis.hgetall(_key(str(meeting_id)))
        if not raw:
            return {"calls": 0, "total_tokens": 0, "estimated_usd": 0.0, "by_agent": {}}

        def _i(k: str) -> int:
            v = raw.get(k) or raw.get(k.encode()) or 0
            return int(v)

        prompt = _i("prompt_tokens")
        completion = _i("completion_tokens")
        by_agent = {}
        for k, v in raw.items():
            ks = k.decode() if isinstance(k, bytes) else k
            if ks.startswith("agent:") and ks.endswith(":tokens"):
                by_agent[ks.split(":")[1]] = int(v)

        return {
            "calls": _i("calls"),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "estimated_usd": round(_i("micro_usd") / 1_000_000, 4),
            "by_agent": by_agent,
        }
    except Exception:
        return {"calls": 0, "total_tokens": 0, "estimated_usd": 0.0, "by_agent": {}}
