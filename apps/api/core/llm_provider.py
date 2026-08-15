"""
Provider resolution and failover from OpenAI to Ollama.

Why this module exists
----------------------
OpenAI is a hard dependency of almost every code path in Donna: the 19 agents,
the query planner, the RAG synthesiser, the embedding pipeline. When the
account's credit balance is exhausted, every one of those paths returns a 429
and the product stops working end to end. That is a bad failure mode for a
demo, for local development, and for any environment without billing.

Ollama exposes an OpenAI-compatible API at ``/v1``, so the *transport* is a
drop-in swap: same client class, same request shape. What is not a drop-in swap
is the meaning of the numbers that come back.

Two Ollama endpoints, not one
-----------------------------
There are two Ollama backends here and they are not interchangeable:

  * **Ollama Cloud** (``https://ollama.com/v1``, needs ``OLLAMA_API_KEY``) —
    hosted models in the ``gpt-oss:120b`` / ``qwen3.5:397b`` class. Far closer
    to GPT-4o than anything that runs on a laptop, so this is the preferred
    chat fallback. Its catalogue is **chat models only**: it publishes no
    embedding model, so an embedding call there fails with a 404, not a
    degraded vector.

  * **Local Ollama** (``http://host.docker.internal:11434/v1``) — runs
    ``nomic-embed-text``, and is therefore the *only* place a fallback
    embedding can come from. Also serves chat when no cloud key is set, so the
    system still works with no account and no network.

Hence ``active_provider()`` (chat) and ``embedding_provider()`` resolve
separately, and during a failover the two legitimately point at different
machines: chat on cloud, embeddings on localhost.

The asymmetry that drives the whole design
------------------------------------------
Chat and embeddings fail over very differently, and conflating them is the
mistake this module is built to prevent.

  * **Chat is safe to fail over.** Text goes in, text comes out. A weaker model
    gives a worse answer, but a worse answer is still an answer of the same
    kind. Nothing persists, nothing is corrupted, and the next call can go
    straight back to OpenAI.

  * **Embeddings are NOT safe to fail over naively.** An embedding is only
    meaningful relative to other embeddings produced by the *same model*.
    ``text-embedding-3-small`` emits 1536 dimensions; ``nomic-embed-text``
    emits 768. Even at equal dimensionality the axes would be unrelated —
    cosine similarity between vectors from two different models is noise
    wearing the costume of a score.

    So writing Ollama vectors into a collection built from OpenAI vectors does
    not "degrade" retrieval. It silently poisons it, permanently, in a way that
    still returns confident-looking results with plausible scores. There is no
    error to notice and no obvious symptom until someone checks whether the
    answers are actually right.

    (This codebase already contains one instance of exactly that mistake:
    ``EmbeddingService`` zero-pads a 384-dim sentence-transformers vector out
    to 1536 so it "fits". It fits the way a wrong key fits a lock you've filed
    down. That path stays off by default and is not extended here.)

The rule this module enforces: **one vector space per embedding model.**
Collections are named after the model that filled them, so an Ollama vector
physically cannot land in an OpenAI collection. Failing over then becomes an
honest, visible, reversible degradation — content indexed under the other
provider is *not found* rather than *wrongly ranked* — instead of silent
corruption. Restoring credits and switching back makes the original corpus
searchable again, untouched.

Failover behaviour
------------------
``LLM_PROVIDER`` selects the policy:

  ``auto``   — prefer OpenAI, latch to Ollama on quota/auth/connectivity
               failure, retry OpenAI after a cooldown. (default)
  ``openai`` — OpenAI only; fail loudly. Correct for production.
  ``ollama`` — Ollama only; never call OpenAI. Correct for offline dev and for
               running on purpose while OpenAI credits are out, since it skips
               the doomed OpenAI attempt on the first call after each cooldown.

Only *systemic* errors trip the latch — the kind that will affect the next call
too (credit exhausted, invalid key, connection refused). A 400 on one malformed
request is that request's problem and must not reroute the whole process.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from openai import AsyncOpenAI

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

# How long to stay on Ollama after OpenAI trips the latch, before probing
# OpenAI again. Long enough that a sustained outage doesn't generate a retry
# storm; short enough that topping up credits takes effect without a restart.
FAILOVER_COOLDOWN_S = 300

# Ollama is a local process. It should answer fast or not at all — a slow local
# model blocking a live-meeting agent is worse than that agent skipping a turn.
OLLAMA_TIMEOUT_S = 60.0
# Cloud gets longer: it runs much larger models (120B class) and a cold start
# on a free tier can take a while before the first token.
OLLAMA_CLOUD_TIMEOUT_S = 120.0
OLLAMA_HEALTH_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Provider:
    """A resolved backend: where to send calls and what to call things there."""

    name: str  # "openai" | "ollama" | "ollama-cloud"
    base_url: Optional[str]
    api_key: str
    chat_fast: str
    chat_smart: str
    embed_model: str
    embed_dims: int
    timeout: Optional[float] = None

    @property
    def is_local(self) -> bool:
        """Running on this machine — used to size batches conservatively."""
        return self.name == "ollama"

    @property
    def is_ollama(self) -> bool:
        """Served by Ollama's OpenAI shim, local or cloud.

        The shim rejects a few OpenAI-only parameters, so anything that has to
        be stripped must key off this rather than ``is_local``.
        """
        return self.name in ("ollama", "ollama-cloud")

    def space_id(self) -> str:
        """Identity of the vector space this provider's embeddings live in.

        Two providers share a space only if they'd produce comparable vectors —
        which in practice means being the same model at the same width.
        """
        return f"{self.name}:{self.embed_model}:{self.embed_dims}"


def _openai_provider() -> Provider:
    return Provider(
        name="openai",
        base_url=None,
        api_key=settings.openai_api_key or "",
        chat_fast=settings.model_fast,
        chat_smart=settings.model_smart,
        embed_model=settings.embedding_model,
        embed_dims=settings.embedding_dimensions,
    )


def _ollama_local_provider() -> Provider:
    """Ollama running on the host. The only source of fallback embeddings."""
    return Provider(
        name="ollama",
        base_url=settings.ollama_base_url.rstrip("/") + "/v1",
        # Local Ollama ignores the key, but the OpenAI SDK refuses to
        # construct without a non-empty one.
        api_key="ollama",
        chat_fast=settings.ollama_chat_model,
        chat_smart=settings.ollama_chat_model_smart or settings.ollama_chat_model,
        embed_model=settings.ollama_embedding_model,
        embed_dims=settings.ollama_embedding_dimensions,
        timeout=OLLAMA_TIMEOUT_S,
    )


def _ollama_cloud_provider() -> Provider:
    """Ollama Cloud — hosted models, CHAT ONLY.

    The cloud catalogue is entirely chat models; it serves no embedding model,
    so ``embed_model`` here is deliberately the *local* one. Nothing should
    ever route an embedding call to this provider — ``embedding_provider()``
    never returns it — but carrying the local values keeps the dataclass
    honest rather than holding a model name that does not exist.
    """
    return Provider(
        name="ollama-cloud",
        base_url=settings.ollama_cloud_base_url.rstrip("/") + "/v1",
        api_key=settings.ollama_api_key or "",
        chat_fast=settings.ollama_cloud_chat_model,
        chat_smart=settings.ollama_cloud_chat_model_smart
        or settings.ollama_cloud_chat_model,
        embed_model=settings.ollama_embedding_model,
        embed_dims=settings.ollama_embedding_dimensions,
        timeout=OLLAMA_CLOUD_TIMEOUT_S,
    )


def cloud_available() -> bool:
    return bool(settings.ollama_api_key)


def _fallback_chat_provider() -> Provider:
    """Where chat goes when OpenAI is unusable.

    Cloud when a key is configured — ``gpt-oss:120b`` is far closer to GPT-4o
    than anything that fits on a laptop — and local Ollama otherwise, which
    still works with no account and no network.
    """
    return _ollama_cloud_provider() if cloud_available() else _ollama_local_provider()


# --------------------------------------------------------------------------
# Failover latch
# --------------------------------------------------------------------------


class _Latch:
    """Tracks whether OpenAI is currently believed to be unusable.

    Deliberately process-local and lock-free. Workers each keep their own view;
    a shared latch would need Redis on the hot path to save, at most, a few
    duplicate probe calls per worker per cooldown window. Not worth it.
    """

    def __init__(self) -> None:
        self.tripped_at: Optional[float] = None
        self.reason: str = ""
        self.trip_count: int = 0

    def trip(self, reason: str) -> None:
        first = self.tripped_at is None
        self.tripped_at = time.monotonic()
        self.reason = reason
        self.trip_count += 1
        if first:
            chat = _fallback_chat_provider()
            logger.error(
                "OpenAI unavailable (%s) for %ds. Chat → %s (%s); embeddings → "
                "local Ollama (%s, %dd), since Ollama Cloud serves no embedding "
                "model. Any corpus indexed with OpenAI embeddings will not be "
                "searchable until OpenAI is restored.",
                reason,
                FAILOVER_COOLDOWN_S,
                chat.name,
                chat.chat_fast,
                settings.ollama_embedding_model,
                settings.ollama_embedding_dimensions,
            )

    def active(self) -> bool:
        if self.tripped_at is None:
            return False
        if time.monotonic() - self.tripped_at >= FAILOVER_COOLDOWN_S:
            logger.info("OpenAI failover cooldown elapsed — retrying OpenAI.")
            self.tripped_at = None
            self.reason = ""
            return False
        return True

    def clear(self) -> None:
        if self.tripped_at is not None:
            logger.info("OpenAI recovered — routing restored.")
        self.tripped_at = None
        self.reason = ""


_latch = _Latch()


# Error signatures that mean "the next call will fail the same way".
# Matched against the stringified exception because the OpenAI SDK surfaces
# these as several different exception classes with the detail in the body.
_SYSTEMIC_PATTERNS = (
    "insufficient_quota",
    "credit_balance",
    "credit balance is too low",
    "exceeded your current quota",
    "billing_hard_limit_reached",
    "account_deactivated",
    "invalid_api_key",
    "incorrect api key",
    "connection error",
    "connection refused",
    "name or service not known",
    "temporary failure in name resolution",
)


def is_systemic_failure(exc: BaseException) -> bool:
    """Would this error recur on the next call, regardless of the request?

    Rate limits are the interesting case. A 429 for *quota* is systemic — no
    amount of waiting fixes an empty balance. A 429 for *requests per minute*
    is transient and must not trip the latch, or a traffic spike would silently
    demote the whole process to a local 3B model.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(p in text for p in _SYSTEMIC_PATTERNS):
        return True
    # Bare 401/403: the key itself is bad.
    if re.search(r"\b(401|403)\b", text) and "rate" not in text:
        return True
    return False


def note_failure(exc: BaseException) -> bool:
    """Report a call failure. Returns True if it tripped failover."""
    if settings.llm_provider != "auto":
        return False
    if not is_systemic_failure(exc):
        return False
    _latch.trip(type(exc).__name__)
    return True


def note_success() -> None:
    """Report an OpenAI call that worked, clearing any latch."""
    if _latch.tripped_at is not None:
        _latch.clear()


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def active_provider() -> Provider:
    """The backend CHAT calls should go to right now."""
    mode = settings.llm_provider
    if mode == "ollama":
        return _fallback_chat_provider()
    if mode == "openai":
        return _openai_provider()
    # auto
    if not settings.openai_api_key:
        return _fallback_chat_provider()
    return _fallback_chat_provider() if _latch.active() else _openai_provider()


def embedding_provider() -> Provider:
    """The backend that should produce EMBEDDINGS right now.

    Resolves separately from chat, and deliberately never returns the cloud
    provider: Ollama Cloud's catalogue is chat models only, so an embedding
    call there would 404. When OpenAI is unusable, embeddings go to the local
    Ollama instance — the only fallback that can actually produce a vector.

    Callers must respect ``space_id()``: this says *which* model to embed with,
    and it is the vector store's job to ensure the result lands in that model's
    own collection and nowhere else.
    """
    mode = settings.llm_provider
    if mode == "ollama":
        return _ollama_local_provider()
    if mode == "openai":
        return _openai_provider()
    if not settings.openai_api_key:
        return _ollama_local_provider()
    return _ollama_local_provider() if _latch.active() else _openai_provider()


def collection_prefix() -> str:
    """Qdrant collection prefix for the *current* embedding space.

    This is the mechanism that makes embedding failover safe. Vectors from two
    different models are not comparable, so they must never share a collection.
    Rather than relying on every call site to remember that, the collection
    name itself carries the model identity — an Ollama vector has nowhere to go
    except an Ollama collection, and Qdrant rejects a 768-dim write into a
    1536-dim collection anyway, so a mistake here fails loudly instead of
    silently degrading recall.

    OpenAI keeps the bare, unsuffixed name because that is what every existing
    collection was built under, whatever ``EMBEDDING_MODEL`` happens to be set
    to. Suffixing it would silently orphan an already-indexed corpus — the data
    would still be there, just at a name nothing looks at any more. Only the
    fallback provider gets a namespace of its own, which is the only place a
    second, incompatible vector space can actually appear.
    """
    p = embedding_provider()
    base = settings.qdrant_collection_name
    if p.name == "openai":
        return base
    slug = re.sub(r"[^a-z0-9]+", "_", f"{p.embed_model}".lower()).strip("_")
    return f"{base}__{slug}_{p.embed_dims}"


_clients: Dict[str, AsyncOpenAI] = {}
_clients_lock = asyncio.Lock()


def client_for(provider: Provider) -> AsyncOpenAI:
    """A cached client for a provider. Cheap enough to call per request."""
    key = f"{provider.name}|{provider.base_url}"
    existing = _clients.get(key)
    if existing is not None:
        return existing
    kwargs: Dict[str, Any] = {"api_key": provider.api_key}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    if provider.timeout:
        kwargs["timeout"] = provider.timeout
    created = AsyncOpenAI(**kwargs)
    _clients[key] = created
    return created


def chat_client() -> tuple[AsyncOpenAI, Provider]:
    """Client + provider for a chat call, honouring current failover state."""
    p = active_provider()
    return client_for(p), p


def resolve_model(requested: str, provider: Provider) -> str:
    """Translate an OpenAI model name to this provider's equivalent.

    Call sites name OpenAI models directly (``gpt-4o-mini``, ``gpt-4o``). Ollama
    has never heard of those, so the name has to be mapped rather than passed
    through — an unmapped name produces a 404 from Ollama that looks nothing
    like a quota error and would be confusing to debug.
    """
    if provider.name == "openai":
        return requested
    lowered = (requested or "").lower()
    if "mini" in lowered or "haiku" in lowered or "3.5" in lowered:
        return provider.chat_fast
    return provider.chat_smart


_JSON_HINT = re.compile(r"\bjson\b", re.IGNORECASE)


def _force_json_mode(
    provider: Provider, messages: list, kwargs: Dict[str, Any]
) -> None:
    """Turn on grammar-constrained decoding when the prompt wants JSON.

    Prompts here are written for GPT-4o, which follows "respond ONLY with JSON"
    closely enough that most agents just call ``json.loads`` on the result.
    Smaller models do not: llama3.2:3b answers this codebase's own research
    prompt with unquoted string values — structurally invalid JSON that no
    lenient parser can honestly repair, because an unquoted value containing
    commas and colons is genuinely ambiguous.

    Ollama supports constrained decoding, which makes malformed output
    impossible rather than unlikely. Enabling it whenever the prompt mentions
    JSON is what lets a 3B fallback drive agents built for a frontier model.

    Note that this mode always yields an *object*: a prompt asking for a bare
    array gets ``{"items": [...]}`` or similar. ``json_parse.loads_array``
    unwraps that, so callers expecting a list still get one.
    """
    if kwargs.get("response_format") is not None:
        return  # caller was explicit; don't second-guess it
    if kwargs.get("stream"):
        return  # constrained decoding + streaming is not worth the risk
    if kwargs.get("tools") or kwargs.get("functions"):
        return  # tool-calling has its own output contract
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str) and _JSON_HINT.search(content):
            kwargs["response_format"] = {"type": "json_object"}
            return


async def chat_completion(
    *,
    messages: list,
    model: Optional[str] = None,
    smart: bool = False,
    **kwargs: Any,
) -> Any:
    """Run a chat completion with automatic OpenAI → Ollama failover.

    One retry, and only when the first failure is systemic. Anything else
    propagates: a malformed request should surface as a malformed request, not
    be quietly re-run against a different model that may also reject it.
    """
    provider = active_provider()
    requested = model or (settings.model_smart if smart else settings.model_fast)
    client = client_for(provider)

    if provider.is_ollama:
        # Ollama's OpenAI shim rejects some parameters outright.
        kwargs.pop("parallel_tool_calls", None)
        _force_json_mode(provider, messages, kwargs)

    try:
        result = await client.chat.completions.create(
            model=resolve_model(requested, provider),
            messages=messages,
            **kwargs,
        )
        if provider.name == "openai":
            note_success()
        return result
    except Exception as e:
        if provider.name != "openai" or not note_failure(e):
            raise
        fallback = _fallback_chat_provider()
        logger.warning(
            "Retrying chat on %s (%s) after OpenAI failure: %s",
            fallback.name,
            fallback.chat_fast,
            e,
        )
        kwargs.pop("parallel_tool_calls", None)
        _force_json_mode(fallback, messages, kwargs)
        return await client_for(fallback).chat.completions.create(
            model=resolve_model(requested, fallback),
            messages=messages,
            **kwargs,
        )


# --------------------------------------------------------------------------
# Drop-in client
# --------------------------------------------------------------------------


class _Completions:
    async def create(self, **kwargs: Any) -> Any:
        return await chat_completion(
            messages=kwargs.pop("messages"),
            model=kwargs.pop("model", None),
            **kwargs,
        )


class _Chat:
    def __init__(self) -> None:
        self.completions = _Completions()


class _Embeddings:
    async def create(self, **kwargs: Any) -> Any:
        provider = embedding_provider()
        requested_dims = kwargs.pop("dimensions", None)

        async def _call(p: Provider) -> Any:
            call_kwargs = dict(kwargs)
            call_kwargs["model"] = (
                kwargs.get("model") if p.name == "openai" else p.embed_model
            ) or p.embed_model
            # OpenAI-only Matryoshka truncation; Ollama rejects the parameter.
            if p.name == "openai" and requested_dims:
                call_kwargs["dimensions"] = requested_dims
            return await client_for(p).embeddings.create(**call_kwargs)

        try:
            result = await _call(provider)
            if provider.name == "openai":
                note_success()
            return result
        except Exception as e:
            if provider.name != "openai" or not note_failure(e):
                raise
            fallback = _ollama_local_provider()
            logger.warning(
                "Retrying embeddings on Ollama (%s, %dd) after OpenAI failure. "
                "Vectors land in that model's own collection — see "
                "llm_provider.collection_prefix().",
                fallback.embed_model,
                fallback.embed_dims,
            )
            return await _call(fallback)


class FailoverClient:
    """An ``AsyncOpenAI``-shaped client that reroutes to Ollama on quota loss.

    Exists so the 17 call sites that construct ``AsyncOpenAI`` directly can
    gain failover by changing the constructor line only — their
    ``client.chat.completions.create(...)`` calls keep working unchanged.

    Attribute access falls through to a real OpenAI client, so anything not
    explicitly wrapped (files, audio, moderations) behaves exactly as before,
    without failover. That is deliberate: silently rerouting an API Ollama
    does not implement would produce a confusing error far from its cause.
    """

    def __init__(self) -> None:
        self.chat = _Chat()
        self.embeddings = _Embeddings()

    def __getattr__(self, item: str) -> Any:
        return getattr(client_for(_openai_provider()), item)


def failover_client() -> FailoverClient:
    """Drop-in replacement for ``AsyncOpenAI(api_key=...)``."""
    return FailoverClient()


async def probe(provider: Optional[Provider] = None) -> Dict[str, Any]:
    """Liveness check used by /health and by setup diagnostics."""
    p = provider or _ollama_local_provider()
    out: Dict[str, Any] = {"provider": p.name, "base_url": p.base_url}
    try:
        client = AsyncOpenAI(
            api_key=p.api_key or "none",
            base_url=p.base_url,
            timeout=OLLAMA_HEALTH_TIMEOUT_S,
        )
        models = await client.models.list()
        names = [m.id for m in models.data]
        out["reachable"] = True
        out["model_count"] = len(names)
        # A configured model that isn't pulled (local) or isn't in the
        # catalogue (cloud) is the most common misconfiguration, and it fails
        # at the worst possible moment. Surface it at health-check time.
        out["chat_model_present"] = any(
            n == p.chat_fast or n.split(":")[0] == p.chat_fast.split(":")[0]
            for n in names
        )
        # Only meaningful for the local instance — Ollama Cloud publishes no
        # embedding models at all, which is exactly why embeddings never fail
        # over to it.
        if p.name == "ollama":
            out["embed_model_present"] = any(
                n == p.embed_model or n.split(":")[0] == p.embed_model.split(":")[0]
                for n in names
            )
    except Exception as e:
        out["reachable"] = False
        out["error"] = str(e)[:200]
    return out


async def probe_all() -> Dict[str, Any]:
    """Probe both fallback endpoints. Used by /health and `make check-fallback`."""
    results = await asyncio.gather(
        probe(_ollama_local_provider()),
        probe(_ollama_cloud_provider()) if cloud_available() else _noop_probe(),
    )
    return {"local": results[0], "cloud": results[1]}


async def _noop_probe() -> Dict[str, Any]:
    return {
        "provider": "ollama-cloud",
        "reachable": False,
        "error": "OLLAMA_API_KEY not set — cloud fallback disabled",
    }


def status() -> Dict[str, Any]:
    """Current routing state, for /health and the UI.

    Chat and embeddings are reported separately because they can legitimately
    be on different backends: during a failover, chat runs on Ollama Cloud
    while embeddings run on local Ollama.
    """
    chat = active_provider()
    embed = embedding_provider()
    return {
        "mode": settings.llm_provider,
        "chat_provider": chat.name,
        "chat_model": chat.chat_fast,
        "chat_model_smart": chat.chat_smart,
        "embedding_provider": embed.name,
        "embedding_model": embed.embed_model,
        "embedding_dimensions": embed.embed_dims,
        "embedding_space": embed.space_id(),
        "failover_active": _latch.active(),
        "failover_reason": _latch.reason or None,
        "failover_count": _latch.trip_count,
        "cloud_configured": cloud_available(),
        "ollama_cloud_base_url": settings.ollama_cloud_base_url,
        "ollama_base_url": settings.ollama_base_url,
    }


def reset_for_tests() -> None:
    """Clear latch and client cache. Test helper only."""
    _latch.tripped_at = None
    _latch.reason = ""
    _latch.trip_count = 0
    _clients.clear()
