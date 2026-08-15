"""
Regression tests for the defect register (see the architecture book, §27).

Each test here pins a fix for a defect that was found by review rather than by
a failing test — which is exactly the class of bug that comes back. The test
name carries the defect id so a future failure is traceable to its story.
"""

import logging

import pytest

from apps.api.core.config import Settings
from apps.api.core.jobs import ALL_QUEUES, QUEUE_BULK, QUEUE_HOT, queue_for
from apps.api.core.llm_meter import _FALLBACK_PRICE, _PRICES, PRICE_TABLE_VERSION
from apps.api.core.logging import warn_throttled
from apps.api.services.meeting.realtime import MeetingHub


# ---------------------------------------------------------------------------
# D2 — production must refuse to boot without auth
# ---------------------------------------------------------------------------
class TestD2ProductionSafety:
    def test_production_without_auth_refuses_to_boot(self):
        cfg = Settings(APP_ENV="production", REQUIRE_AUTH=False, JWT_SECRET="x")
        with pytest.raises(RuntimeError, match="REQUIRE_AUTH"):
            cfg.assert_production_safe()

    def test_production_with_default_jwt_secret_refuses_to_boot(self):
        # Passed explicitly: a developer's .env may define a real secret, and
        # the assertion under test is about the *value*, not where it came from.
        cfg = Settings(
            APP_ENV="production",
            REQUIRE_AUTH=True,
            JWT_SECRET="dev-secret-change-in-production",
        )
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            cfg.assert_production_safe()

    def test_safe_production_config_boots(self):
        # ENCRYPTION_KEY joined the gate when customer-database connections
        # shipped: without it, stored DB credentials would be unprotected.
        Settings(
            APP_ENV="production",
            REQUIRE_AUTH=True,
            JWT_SECRET="a-real-secret",
            ENCRYPTION_KEY="a-real-encryption-key",
        ).assert_production_safe()

    def test_production_without_encryption_key_refuses_to_boot(self):
        # _env_file=None isolates this from the developer's own .env, which
        # legitimately has an ENCRYPTION_KEY and would otherwise satisfy the
        # gate this test exists to prove fires.
        cfg = Settings(
            APP_ENV="production",
            REQUIRE_AUTH=True,
            JWT_SECRET="a-real-secret",
            _env_file=None,
        )
        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
            cfg.assert_production_safe()

    def test_development_is_unaffected(self):
        # Auth-off dev/demo must keep working — the gate is production-only.
        Settings(APP_ENV="development", REQUIRE_AUTH=False).assert_production_safe()

    def test_queue_disabled_in_production_warns_but_does_not_block(self):
        cfg = Settings(
            APP_ENV="production",
            REQUIRE_AUTH=True,
            JWT_SECRET="s",
            ENCRYPTION_KEY="k",
            USE_JOB_QUEUE=False,
        )
        cfg.assert_production_safe()  # must not raise
        assert any("USE_JOB_QUEUE" in w for w in cfg.production_safety_warnings())


# ---------------------------------------------------------------------------
# D3 — activation nudges are addressed by email, not display name
# ---------------------------------------------------------------------------
def _activation(email=None, person="Chris", pinned=False):
    return {
        "type": "nudge_created",
        "nudge": {
            "type": "activation",
            "pinned_at": "2026-01-01T00:00:00Z" if pinned else None,
            "source_data": {"person": person, "person_email": email},
        },
    }


class TestD3ActivationAddressing:
    CHRIS_A = {"role": "participant", "name": "Chris", "email": "chris.a@corp.com"}
    CHRIS_B = {"role": "participant", "name": "Chris", "email": "chris.b@corp.com"}

    def test_addressee_receives_their_own_activation(self):
        n = _activation(email="chris.a@corp.com")
        assert MeetingHub._visible_to(n, self.CHRIS_A) is True

    def test_same_named_participant_does_not_receive_it(self):
        """The defect: two attendees named 'Chris' saw each other's nudges."""
        n = _activation(email="chris.a@corp.com")
        assert MeetingHub._visible_to(n, self.CHRIS_B) is False

    def test_email_match_is_case_insensitive(self):
        n = _activation(email="Chris.A@Corp.com")
        assert MeetingHub._visible_to(n, self.CHRIS_A) is True

    def test_participant_without_identity_gets_nothing(self):
        n = _activation(email="chris.a@corp.com")
        anon = {"role": "participant", "name": None, "email": None}
        assert MeetingHub._visible_to(n, anon) is False

    def test_legacy_nudge_without_email_falls_back_to_name(self):
        """Nudges persisted before person_email existed must still resolve."""
        assert MeetingHub._visible_to(_activation(email=None), self.CHRIS_A) is True

    def test_leader_still_sees_everything(self):
        n = _activation(email="chris.a@corp.com")
        assert MeetingHub._visible_to(n, {"role": "leader"}) is True

    def test_pinned_nudges_reach_every_participant(self):
        n = _activation(email="chris.a@corp.com", pinned=True)
        assert MeetingHub._visible_to(n, self.CHRIS_B) is True

    def test_unpinned_non_activation_nudge_is_hidden_by_default(self):
        payload = {
            "type": "nudge_created",
            "nudge": {"type": "fact_check", "pinned_at": None, "source_data": {}},
        }
        assert MeetingHub._visible_to(payload, self.CHRIS_A) is False


# ---------------------------------------------------------------------------
# D6 — the hot path must not share a queue with bulk work
# ---------------------------------------------------------------------------
class TestD6QueueIsolation:
    def test_dispatch_is_on_the_hot_queue(self):
        assert queue_for("dispatch_job") == QUEUE_HOT

    @pytest.mark.parametrize(
        "job", ["research_job", "summary_job", "process_document_job"]
    )
    def test_bulk_jobs_are_not_on_the_hot_queue(self, job):
        assert queue_for(job) == QUEUE_BULK

    def test_unknown_jobs_default_to_bulk(self):
        """A new job is assumed slow until deliberately promoted."""
        assert queue_for("some_future_job") == QUEUE_BULK

    def test_workers_consume_disjoint_job_sets(self):
        from apps.workers.job_worker import DispatchWorkerSettings, WorkerSettings

        bulk = {f.__name__ for f in WorkerSettings.functions}
        hot = {f.__name__ for f in DispatchWorkerSettings.functions}
        assert hot == {"dispatch_job"}
        assert not (bulk & hot), "a job consumed by both workers can run twice"
        assert WorkerSettings.queue_name == QUEUE_BULK
        assert DispatchWorkerSettings.queue_name == QUEUE_HOT

    def test_cron_runs_only_on_the_bulk_worker(self):
        from apps.workers.job_worker import DispatchWorkerSettings, WorkerSettings

        assert WorkerSettings.cron_jobs
        assert not hasattr(DispatchWorkerSettings, "cron_jobs")

    def test_all_queues_are_distinct(self):
        assert len(set(ALL_QUEUES)) == len(ALL_QUEUES)


# ---------------------------------------------------------------------------
# D5 — cost figures carry the price table that produced them
# ---------------------------------------------------------------------------
class TestD5PriceProvenance:
    def test_price_table_is_versioned(self):
        assert PRICE_TABLE_VERSION

    def test_unknown_models_bill_at_fallback_not_free(self):
        """An unrecognized model must over-report, never silently cost $0."""
        assert _FALLBACK_PRICE == (2.50, 10.00)
        assert _FALLBACK_PRICE[0] > 0 and _FALLBACK_PRICE[1] > 0

    def test_configured_model_tiers_are_priced(self):
        for model in ("gpt-4o-mini", "gpt-4o", "text-embedding-3-small"):
            assert model in _PRICES, f"{model} is in use but unpriced"

    def test_fast_tier_is_cheaper_than_smart_tier(self):
        assert _PRICES["gpt-4o-mini"][0] < _PRICES["gpt-4o"][0]


# ---------------------------------------------------------------------------
# D7 — degradation must be visible, and must not flood
# ---------------------------------------------------------------------------
class TestD7ThrottledWarnings:
    def _capture(self, name):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = False
        records = []

        class H(logging.Handler):
            def emit(self, r):
                records.append(r)

        log.addHandler(H())
        log.setLevel(logging.WARNING)
        return log, records

    def test_emits_at_warning_not_debug(self):
        """The whole defect: these logged at DEBUG, i.e. nowhere in production."""
        log, records = self._capture("t.d7.level")
        warn_throttled(log, "k.level", "redis down", interval_seconds=60)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING

    def test_repeated_failures_emit_once_per_interval(self):
        log, records = self._capture("t.d7.throttle")
        for _ in range(500):
            warn_throttled(log, "k.throttle", "redis down", interval_seconds=60)
        assert len(records) == 1, "a per-request failure path must not flood"

    def test_suppressed_count_is_reported(self):
        log, records = self._capture("t.d7.count")
        for _ in range(10):
            warn_throttled(log, "k.count", "redis down", interval_seconds=60)
        warn_throttled(log, "k.count", "redis down", interval_seconds=0)
        assert "repeated 9x" in records[-1].getMessage()

    def test_distinct_keys_do_not_suppress_each_other(self):
        log, records = self._capture("t.d7.keys")
        warn_throttled(log, "k.a", "a", interval_seconds=60)
        warn_throttled(log, "k.b", "b", interval_seconds=60)
        assert len(records) == 2


# ---------------------------------------------------------------------------
# Groundedness gating of spoken nudges
# ---------------------------------------------------------------------------
class TestSpokenFactCheckMustBeGrounded:
    """Donna must never SAY ALOUD an explanation her own sources don't support.

    fact_check is one of only two nudge types eligible for text-to-speech, and
    the explanation is LLM-generated prose about someone's spoken claim. An
    invented figure would be asserted to the room with a citation attached —
    which makes it more credible, not less. The rule: an ungrounded
    explanation may still be SHOWN (with sources, for a human to judge) but is
    capped below the speech threshold.
    """

    def test_speak_threshold_is_what_the_cap_targets(self):
        from apps.api.services.meeting.agent_dispatcher import (
            _SPEAK_MIN_RELEVANCE,
            _SPEAK_TYPES,
        )

        assert "fact_check" in _SPEAK_TYPES
        # The cap applied to ungrounded explanations (0.75) must sit strictly
        # below the speech threshold, or the suppression does nothing.
        assert 0.75 < _SPEAK_MIN_RELEVANCE

    def test_grounded_explanation_keeps_its_confidence(self):
        from apps.api.services.rag.groundedness import assess

        sources = ["Revenue grew 15% year over year, reaching $4.2M in Q3."]
        report = assess("The sources confirm revenue grew 15% to $4.2M.", sources)
        assert report.label == "supported"

    def test_fabricated_figure_in_explanation_is_detected(self):
        from apps.api.services.rag.groundedness import assess

        sources = ["Revenue grew 15% year over year, reaching $4.2M in Q3."]
        report = assess("Actually revenue grew 40%, reaching $9.1M.", sources)
        assert report.label != "supported", (
            "a figure absent from the sources must not pass as grounded — "
            "this is the case that would otherwise be spoken aloud"
        )
        assert report.unsupported_claims


# ---------------------------------------------------------------------------
# D10 — every model must be registered, or foreign keys fail at INSERT time
# ---------------------------------------------------------------------------
class TestD10ModelRegistry:
    """SQLAlchemy resolves FKs against Base.metadata at statement-compile time.

    The defect: `main.py` imported the `Document` model only inside function
    bodies, so at startup `doc_intel.analytics_events` was registered but
    `doc_intel.documents` was not. Every analytics write then failed FK
    resolution — swallowed by track_event's except-and-log, so telemetry
    silently wrote nothing while the app looked healthy. It would start
    working after any request that happened to import Document, making it
    intermittent and order-dependent.
    """

    def test_importing_one_model_registers_all(self):
        """Importing the package must be sufficient — no call-site discipline."""
        import apps.api.models  # noqa: F401
        from apps.api.core.database import Base

        registered = set(Base.metadata.tables)
        for table in (
            "doc_intel.documents",
            "doc_intel.analytics_events",
            "doc_intel.meetings",
            "doc_intel.nudges",
            "doc_intel.users",
            "doc_intel.kg_outbox",
        ):
            assert table in registered, f"{table} missing from metadata"

    def test_every_foreign_key_target_is_registered(self):
        """The general form: no FK may point at an unregistered table.

        This catches the whole class of bug, not just the one instance —
        a new model with an FK to an unlisted table fails here.
        """
        import apps.api.models  # noqa: F401
        from apps.api.core.database import Base

        registered = set(Base.metadata.tables)
        dangling = []
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                target = fk.target_fullname.rsplit(".", 1)[0]
                if target not in registered:
                    dangling.append(f"{table.name}.{fk.parent.name} -> {target}")
        assert not dangling, (
            "foreign keys pointing at unregistered tables (these fail at "
            f"INSERT, not at import): {dangling}"
        )

    def test_registry_lists_every_model_module(self):
        """A model module absent from __init__ reintroduces the defect."""
        from pathlib import Path

        import apps.api.models as pkg

        src = Path(pkg.__file__).read_text()
        model_modules = {
            p.stem
            for p in Path(pkg.__file__).parent.glob("*.py")
            # requests/responses are Pydantic schemas, not ORM models.
            if p.stem not in ("__init__", "requests", "responses")
        }
        missing = [m for m in model_modules if f"models.{m} import" not in src]
        assert not missing, (
            f"model modules not imported in models/__init__.py: {missing}"
        )
