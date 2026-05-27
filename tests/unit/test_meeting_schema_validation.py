"""
Tests for Phase-A input validation hardening:
  * DecisionCreate / ActionItemCreate reject malformed UUIDs (→ 422 in the
    API) instead of letting them reach ``UUID(...)`` in the router (→ 500).
  * Empty strings normalize to None; valid UUIDs normalize to canonical form.
"""

import os
import uuid

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")

import pytest
from pydantic import ValidationError

from apps.api.models.meeting import ActionItemCreate, DecisionCreate


class TestDecisionCreateUUID:
    def test_valid_uuid_normalized(self):
        u = uuid.uuid4()
        d = DecisionCreate(decision_text="Go with Beacon", source_nudge_id=str(u))
        assert d.source_nudge_id == str(u)

    def test_empty_string_becomes_none(self):
        d = DecisionCreate(decision_text="x", source_nudge_id="")
        assert d.source_nudge_id is None

    def test_none_stays_none(self):
        d = DecisionCreate(decision_text="x")
        assert d.source_nudge_id is None

    def test_malformed_uuid_rejected(self):
        with pytest.raises(ValidationError):
            DecisionCreate(decision_text="x", source_nudge_id="not-a-uuid")


class TestActionItemCreateUUID:
    def test_valid_uuid_ok(self):
        u = uuid.uuid4()
        a = ActionItemCreate(description="draft", decision_id=str(u))
        assert a.decision_id == str(u)

    def test_malformed_uuid_rejected(self):
        with pytest.raises(ValidationError):
            ActionItemCreate(description="draft", decision_id="1234-bad")
