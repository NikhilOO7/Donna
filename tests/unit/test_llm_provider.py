"""
Tests for OpenAI → Ollama failover.

The property that matters most here is not "does the fallback work" but
"can the fallback corrupt anything". A weaker chat model is a visible,
recoverable degradation. A 768-dim vector written into a 1536-dim space, or a
query embedded by one model and searched against another's vectors, produces
confident nonsense that nothing alerts on. So most of these tests are about
keeping the two embedding spaces apart.
"""

from unittest.mock import AsyncMock, patch

import pytest

from apps.api.core import llm_provider as lp
from apps.api.core.config import settings


@pytest.fixture(autouse=True)
def _reset():
    lp.reset_for_tests()
    yield
    lp.reset_for_tests()


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 429 - insufficient_quota: You exceeded your current quota",
        "429 {'code': 'credit_balance_exhausted'}",
        "Your credit balance is too low to access the API",
        "APIConnectionError: Connection error.",
        "401 invalid_api_key",
        "billing_hard_limit_reached",
    ],
)
def test_systemic_failures_trip_failover(message):
    assert lp.is_systemic_failure(RuntimeError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        # The important negative: a per-minute rate limit is transient. Treating
        # it as systemic would demote the whole process to a local 3B model
        # every time traffic spikes.
        "429 Rate limit reached for gpt-4o-mini in organization org-x on requests per min",
        "400 Bad Request: invalid 'messages'",
        "500 internal server error",
        "context_length_exceeded",
    ],
)
def test_transient_failures_do_not_trip_failover(message):
    assert lp.is_systemic_failure(RuntimeError(message)) is False


def test_latch_only_arms_in_auto_mode():
    with patch.object(settings, "llm_provider", "openai"):
        assert lp.note_failure(RuntimeError("insufficient_quota")) is False
        assert lp.active_provider().name == "openai"


def test_success_clears_latch():
    lp.note_failure(RuntimeError("insufficient_quota"))
    assert lp.active_provider().name != "openai"
    lp.note_success()
    assert lp.active_provider().name == "openai"


def test_cooldown_expiry_retries_openai(monkeypatch):
    lp.note_failure(RuntimeError("insufficient_quota"))
    assert lp.active_provider().name != "openai"

    base = lp._latch.tripped_at
    monkeypatch.setattr(lp.time, "monotonic", lambda: base + lp.FAILOVER_COOLDOWN_S + 1)
    assert lp.active_provider().name == "openai"


def test_explicit_modes_pin_the_provider():
    # Pin the cloud key so this asserts the mode, not the ambient .env.
    with patch.object(settings, "llm_provider", "ollama"):
        with patch.object(settings, "ollama_api_key", None):
            assert lp.active_provider().name == "ollama"
        with patch.object(settings, "ollama_api_key", "k"):
            assert lp.active_provider().name == "ollama-cloud"
    with patch.object(settings, "llm_provider", "openai"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        assert lp.active_provider().name == "openai"


# --------------------------------------------------------------------------
# Cloud vs local split
#
# Ollama Cloud publishes 18 chat models and zero embedding models, so chat and
# embeddings cannot fail over to the same place.
# --------------------------------------------------------------------------


def test_chat_prefers_cloud_when_key_is_set():
    with patch.object(settings, "ollama_api_key", "test-key"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        assert lp.active_provider().name == "ollama-cloud"


def test_chat_uses_local_when_no_cloud_key():
    with patch.object(settings, "ollama_api_key", None):
        lp.note_failure(RuntimeError("insufficient_quota"))
        assert lp.active_provider().name == "ollama"


def test_embeddings_never_route_to_cloud():
    """The invariant that keeps embedding failover from 404-ing.

    Ollama Cloud has no embedding model at all. If ``embedding_provider()``
    ever returned it, every indexing job would fail the moment OpenAI ran out
    of credit — which is exactly the situation the fallback exists for.
    """
    with patch.object(settings, "ollama_api_key", "test-key"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        assert lp.active_provider().name == "ollama-cloud"
        assert lp.embedding_provider().name == "ollama"

    with patch.object(settings, "llm_provider", "ollama"):
        with patch.object(settings, "ollama_api_key", "test-key"):
            assert lp.embedding_provider().name == "ollama"


def test_embedding_provider_points_at_local_host():
    with patch.object(settings, "ollama_api_key", "test-key"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        embed = lp.embedding_provider()
        assert embed.base_url == settings.ollama_base_url.rstrip("/") + "/v1"
        assert "ollama.com" not in (embed.base_url or "")


def test_cloud_models_are_ollama_shim_flavoured():
    cloud = lp._ollama_cloud_provider()
    # Not "local", but still Ollama's shim — parameter stripping must apply.
    assert cloud.is_local is False
    assert cloud.is_ollama is True
    assert lp._ollama_local_provider().is_ollama is True
    assert lp._openai_provider().is_ollama is False


def test_status_reports_both_legs_separately():
    with patch.object(settings, "ollama_api_key", "test-key"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        s = lp.status()
        assert s["chat_provider"] == "ollama-cloud"
        assert s["embedding_provider"] == "ollama"
        assert s["failover_active"] is True
        assert s["cloud_configured"] is True


# --------------------------------------------------------------------------
# Vector-space isolation — the corruption-prevention invariant
# --------------------------------------------------------------------------


def test_providers_never_share_a_collection():
    # Embeddings never use cloud, so this holds with or without a key.
    openai_prefix = lp.collection_prefix()
    lp.note_failure(RuntimeError("insufficient_quota"))
    ollama_prefix = lp.collection_prefix()

    assert openai_prefix != ollama_prefix
    # Not merely different — the fallback's name must not be a prefix of the
    # baseline's either, or suffixed level collections could still collide.
    assert not ollama_prefix.startswith(openai_prefix + "_local")


def test_openai_keeps_the_unsuffixed_name():
    """An already-indexed corpus must stay at the name it was written under.

    Renaming it would not lose the data, but nothing would ever look at it
    again — a silent, total loss of retrieval that looks like an empty index.
    """
    assert lp.collection_prefix() == settings.qdrant_collection_name


def test_fallback_collection_name_encodes_model_and_width():
    lp.note_failure(RuntimeError("insufficient_quota"))
    prefix = lp.collection_prefix()
    assert str(settings.ollama_embedding_dimensions) in prefix
    assert "nomic" in prefix.lower()


def test_space_id_separates_providers():
    openai_space = lp.embedding_provider().space_id()
    lp.note_failure(RuntimeError("insufficient_quota"))
    assert lp.embedding_provider().space_id() != openai_space


def test_declared_dimensions_match_across_config():
    """Guards the setting that decides collection width."""
    assert settings.ollama_embedding_dimensions > 0
    assert settings.ollama_embedding_dimensions != settings.embedding_dimensions, (
        "If the two providers ever share a dimension, the collection-name "
        "suffix is the only thing keeping their vectors apart. That is still "
        "correct, but this test exists to make the change deliberate."
    )


# --------------------------------------------------------------------------
# Width verification
# --------------------------------------------------------------------------


async def test_wrong_width_is_rejected_not_padded():
    """A vector that doesn't match the declared width must raise.

    Padding or truncating it to fit is the failure mode this whole design
    exists to prevent: the write succeeds, retrieval keeps returning results,
    and the results are meaningless.
    """
    from apps.api.services.document.embeddings import ContextualEmbeddingGenerator

    gen = ContextualEmbeddingGenerator.__new__(ContextualEmbeddingGenerator)
    provider = lp._ollama_local_provider()  # declares 768

    fake = AsyncMock()
    fake.embeddings.create = AsyncMock(
        return_value=type(
            "R", (), {"data": [type("D", (), {"embedding": [0.1] * 384})()]}
        )()
    )

    with patch.object(lp, "client_for", return_value=fake):
        with patch(
            "apps.api.core.cache.get_cached_embedding", AsyncMock(return_value=None)
        ):
            with pytest.raises(ValueError, match="384-dim"):
                await gen._embed_one("hello", provider)


async def test_batch_does_not_split_across_spaces():
    """A failing batch retries wholly on the fallback, never partially.

    A document half-indexed in one space and half in another is worse than one
    that failed outright: each half is invisible to queries embedded for the
    other, and nothing reports an error.
    """
    from apps.api.services.document.contextual_processor import (
        ContextualEmbeddingGenerator as BatchGenerator,
    )

    gen = BatchGenerator.__new__(BatchGenerator)
    seen = []

    async def fake_batch_with(texts, provider):
        seen.append((provider.name, len(texts)))
        if provider.name == "openai":
            raise RuntimeError("Error code: 429 - insufficient_quota")
        return [[0.0] * provider.embed_dims for _ in texts]

    gen._embed_batch_with = fake_batch_with
    out = await gen._embed_batch(["a", "b", "c"])

    assert [p for p, _ in seen] == ["openai", "ollama"]
    # Whole batch on each attempt — no partial handoff.
    assert {n for _, n in seen} == {3}
    assert len(out) == 3
    assert len(out[0]) == settings.ollama_embedding_dimensions


# --------------------------------------------------------------------------
# Model mapping
# --------------------------------------------------------------------------


def test_openai_model_names_are_translated_for_ollama():
    ollama = lp._ollama_local_provider()
    # Passing "gpt-4o-mini" through unchanged would 404 on Ollama with an
    # error that looks nothing like a quota problem.
    assert lp.resolve_model("gpt-4o-mini", ollama) == ollama.chat_fast
    assert lp.resolve_model("gpt-4o", ollama) == ollama.chat_smart
    assert lp.resolve_model("gpt-4o", lp._openai_provider()) == "gpt-4o"


def test_failover_client_exposes_openai_surface():
    client = lp.failover_client()
    assert hasattr(client.chat.completions, "create")
    assert hasattr(client.embeddings, "create")


# --------------------------------------------------------------------------
# Resilience must follow the provider, not the declared service name
# --------------------------------------------------------------------------


def test_breaker_key_and_timeout_follow_the_active_provider():
    """Agents declare service_name="openai" but may be served by Ollama.

    Two things must move with the real backend:

      * the breaker key — otherwise a slow Ollama response trips the OpenAI
        breaker, which then rejects calls that would have gone to Ollama. The
        breaker ends up guarding a service nobody is calling while blocking
        the one that still works.
      * the timeout — the per-agent budgets are tuned for gpt-4o-mini, and a
        20B reasoning model does not answer a live-meeting agent in 10s.
    """
    from apps.api.core.resilience import _effective_target

    svc, budget = _effective_target(10.0)
    assert svc == "openai"
    assert budget == 10.0

    with patch.object(settings, "ollama_api_key", "k"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        svc, budget = _effective_target(10.0)
        assert svc == "ollama-cloud"
        assert budget > 10.0

    lp.reset_for_tests()
    with patch.object(settings, "ollama_api_key", None):
        lp.note_failure(RuntimeError("insufficient_quota"))
        svc, budget = _effective_target(10.0)
        assert svc == "ollama"
        assert budget > 10.0


def test_effective_target_never_raises():
    """This runs on every agent call — it must not be the thing that breaks."""
    from apps.api.core.resilience import _effective_target

    with patch.object(lp, "active_provider", side_effect=RuntimeError("boom")):
        assert _effective_target(12.0) == ("openai", 12.0)


def test_tight_budgets_get_a_usable_floor():
    """A 10s budget x multiplier is still too short for a cold large model."""
    from apps.api.core.resilience import _FALLBACK_MIN_TIMEOUT_S, _effective_target

    with patch.object(settings, "ollama_api_key", None):
        lp.note_failure(RuntimeError("insufficient_quota"))
        _, budget = _effective_target(5.0)
        assert budget >= _FALLBACK_MIN_TIMEOUT_S


# --------------------------------------------------------------------------
# Live-agent budgets
# --------------------------------------------------------------------------


def test_llm_agent_budgets_stretch_on_fallback():
    """The dispatcher's own ceiling has to move with the provider.

    It enforces these with asyncio.wait_for outside resilient_call, so the
    resilience-layer fix alone does nothing — the dispatcher cancels first and
    every LLM agent degrades to None, which looks like Donna having no
    insights at all.
    """
    from apps.api.services.meeting.agent_dispatcher import (
        _AGENT_TIMEOUTS,
        _agent_timeout,
    )

    assert _agent_timeout("insight") == _AGENT_TIMEOUTS["insight"]

    with patch.object(settings, "ollama_api_key", "k"):
        lp.note_failure(RuntimeError("insufficient_quota"))
        assert _agent_timeout("insight") > _AGENT_TIMEOUTS["insight"]
        assert _agent_timeout("scribe") > _AGENT_TIMEOUTS["scribe"]


def test_non_llm_agent_budgets_are_untouched():
    """A slower chat model is no reason to let a graph traversal run longer."""
    from apps.api.services.meeting.agent_dispatcher import (
        _AGENT_TIMEOUTS,
        _agent_timeout,
    )

    lp.note_failure(RuntimeError("insufficient_quota"))
    for name in ("activation", "agenda", "kg_query", "memory", "flow"):
        assert _agent_timeout(name) == _AGENT_TIMEOUTS[name]


def test_agent_budgets_stay_bounded():
    """A live nudge that lands after the moment has passed is worthless."""
    from apps.api.services.meeting.agent_dispatcher import _agent_timeout

    lp.note_failure(RuntimeError("insufficient_quota"))
    for name in ("scribe", "insight", "fact_check", "context"):
        assert _agent_timeout(name) <= 45.0


def test_voice_worker_prewarm_is_module_scoped_and_sync():
    """Two constraints LiveKit imposes on prewarm_fnc, both previously broken.

    Module scope: LiveKit forks job subprocesses that re-import this module and
    resolve prewarm_fnc by name. Defined under `if __name__ == "__main__"` it
    exists only in the parent, and every child dies with AttributeError before
    it can accept a room.

    Synchronous: LiveKit calls it directly rather than awaiting it, so an
    `async def` yields a coroutine that never runs and whatever it was meant to
    start silently doesn't.
    """
    import importlib
    import inspect

    mod = importlib.import_module("apps.workers.meeting_voice_worker")
    assert hasattr(mod, "_prewarm"), (
        "_prewarm must be at module scope or forked voice workers cannot start"
    )
    assert not inspect.iscoroutinefunction(mod._prewarm), (
        "prewarm_fnc is invoked synchronously; an async def is never awaited"
    )
    assert hasattr(mod, "_ensure_heartbeat"), (
        "heartbeat must start from the async entrypoint, which has a loop"
    )
