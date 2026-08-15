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

# USD per 1M tokens (input, output).
#
# BUMP ``PRICE_TABLE_VERSION`` whenever a price changes. Provider price
# changes would otherwise silently invalidate every historical figure with
# nothing in the data to detect it — the version is stamped into each
# meeting's cost hash so a stored figure can be traced back to the table
# that produced it, and mixed-version meetings are detectable rather than
# quietly averaged.
PRICE_TABLE_VERSION = "2026-08-13"

_PRICES: Dict[str, tuple] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4-turbo-preview": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "text-embedding-3-small": (0.02, 0.0),
}

# Unknown models bill at gpt-4o rates: an unrecognized model must over-report
# rather than silently report free. Tracked so the caller can see it happened.
_FALLBACK_PRICE = (2.50, 10.00)

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
        priced = model in _PRICES
        in_price, out_price = _PRICES.get(model, _FALLBACK_PRICE)
        micro_usd = int(prompt * in_price + completion * out_price)  # per 1M → µ$
        pipe.hincrby(key, "micro_usd", micro_usd)
        # Provenance for the figure: which price table produced it, and
        # whether any call in this meeting was billed at fallback rates.
        pipe.hset(key, "price_table_version", PRICE_TABLE_VERSION)
        if not priced:
            pipe.hincrby(key, "unpriced_calls", 1)
        pipe.expire(key, _TTL_SECONDS)
        await pipe.execute()

        if not priced:
            logger.warning(
                f"[llm_meter] no price for model '{model}' — billed at gpt-4o "
                f"fallback rates. Add it to _PRICES and bump PRICE_TABLE_VERSION."
            )
    except Exception as e:
        # Metering must never break the caller, but a silent meter is how a
        # cost figure quietly becomes fiction. Log loudly enough to be seen.
        logger.warning(f"[llm_meter] failed to record usage for '{agent}': {e}")


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

        def _s(k: str) -> Optional[str]:
            v = raw.get(k) or raw.get(k.encode())
            if v is None:
                return None
            return v.decode() if isinstance(v, bytes) else str(v)

        prompt = _i("prompt_tokens")
        completion = _i("completion_tokens")
        by_agent = {}
        for k, v in raw.items():
            ks = k.decode() if isinstance(k, bytes) else k
            if ks.startswith("agent:") and ks.endswith(":tokens"):
                by_agent[ks.split(":")[1]] = int(v)

        stamped = _s("price_table_version")
        unpriced = _i("unpriced_calls")
        return {
            "calls": _i("calls"),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "estimated_usd": round(_i("micro_usd") / 1_000_000, 4),
            "by_agent": by_agent,
            # Provenance: which table priced this, and whether it is still current.
            "price_table_version": stamped,
            "price_table_current": (stamped is None or stamped == PRICE_TABLE_VERSION),
            "unpriced_calls": unpriced,
        }
    except Exception as e:
        logger.warning(f"[llm_meter] failed to read cost for {meeting_id}: {e}")
        return {"calls": 0, "total_tokens": 0, "estimated_usd": 0.0, "by_agent": {}}
