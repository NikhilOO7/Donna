"""End-to-end meeting lifecycle over HTTP with a real database.

Covers the founder-critical path: register → create meeting (structured
type + agenda) → invite a participant → role-scoped visibility →
utterances → transcript → shared canvas → transcript import.

LLM boundaries (agent dispatch, summary pipeline) are patched — this test
verifies the product plumbing, not OpenAI. Skips when Postgres is
unreachable (CI provides it; locally use the compose stack).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# One event loop for the whole module — the app's DB engine pools
# asyncpg connections that are bound to the loop that created them.
pytestmark = pytest.mark.asyncio(loop_scope="module")


async def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from apps.api.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture(loop_scope="module")
async def client():
    if not await _db_available():
        pytest.skip("Postgres unavailable — E2E requires a database")

    from apps.api.main import app

    with (
        patch("apps.api.routers.meetings.enqueue", AsyncMock(return_value=False)),
        patch(
            "apps.api.routers.meetings.agent_dispatcher",
            MagicMock(dispatch=AsyncMock()),
        ),
        patch(
            "apps.api.routers.meetings.summary_pipeline",
            MagicMock(run=AsyncMock()),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as http_client:
            yield http_client


async def _register(client: AsyncClient, name: str) -> tuple[str, str]:
    """Register a fresh user; returns (token, email)."""
    email = f"e2e-{name}-{uuid.uuid4().hex[:10]}@e2e-donna.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "e2e-password-123", "full_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], email


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_full_meeting_lifecycle_single_and_multiplayer(client: AsyncClient):
    leader_token, _ = await _register(client, "leader")
    part_token, part_email = await _register(client, "participant")

    # --- Leader creates a structured meeting -----------------------------
    resp = await client.post(
        "/api/v1/meetings/",
        headers=_auth(leader_token),
        json={
            "title": "E2E Strategy Sync",
            "meeting_type": "Strategy Planning",
            "agenda": ["Review pricing", "Decide vendor"],
        },
    )
    assert resp.status_code == 200, resp.text
    meeting_id = resp.json()["id"]

    detail = (
        await client.get(f"/api/v1/meetings/{meeting_id}", headers=_auth(leader_token))
    ).json()
    assert detail["my_role"] == "leader"
    assert detail["meeting_type"] == "Strategy Planning"
    assert [a["title"] for a in detail["agenda"]] == ["Review pricing", "Decide vendor"]

    # --- Participant cannot see it before the invite ----------------------
    resp = await client.get(f"/api/v1/meetings/{meeting_id}", headers=_auth(part_token))
    assert resp.status_code == 404

    # --- Invite via attendees PATCH ---------------------------------------
    resp = await client.patch(
        f"/api/v1/meetings/{meeting_id}",
        headers=_auth(leader_token),
        json={
            "attendees": [
                {"name": "Pat", "email": part_email, "expertise": ["pricing"]}
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    detail = (
        await client.get(f"/api/v1/meetings/{meeting_id}", headers=_auth(part_token))
    ).json()
    assert detail["my_role"] == "participant"
    assert detail["my_name"] == "Pat"

    listing = (await client.get("/api/v1/meetings/", headers=_auth(part_token))).json()
    assert any(m["id"] == meeting_id for m in listing["meetings"])

    # --- Live phase: utterances flow, leader-only actions enforced --------
    resp = await client.post(
        f"/api/v1/meetings/{meeting_id}/start", headers=_auth(leader_token)
    )
    assert resp.status_code == 200

    resp = await client.post(
        f"/api/v1/meetings/{meeting_id}/utterances",
        headers=_auth(part_token),
        json={"speaker": "Pat", "text": "The pricing model needs a review."},
    )
    assert resp.status_code == 200

    transcript = (
        await client.get(
            f"/api/v1/meetings/{meeting_id}/transcript", headers=_auth(part_token)
        )
    ).json()
    assert len(transcript["utterances"]) == 1

    # Participant cannot end the meeting or repatch attendees
    assert (
        await client.post(
            f"/api/v1/meetings/{meeting_id}/end", headers=_auth(part_token)
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/meetings/{meeting_id}",
            headers=_auth(part_token),
            json={"attendees": []},
        )
    ).status_code == 404

    # --- Shared canvas persists and is visible to the participant ---------
    resp = await client.patch(
        f"/api/v1/meetings/{meeting_id}/canvas",
        headers=_auth(leader_token),
        json={"positions": {"some-nudge": {"x": 120.4, "y": 88.0}}},
    )
    assert resp.status_code == 200
    detail = (
        await client.get(f"/api/v1/meetings/{meeting_id}", headers=_auth(part_token))
    ).json()
    assert detail["canvas_positions"]["some-nudge"]["x"] == 120.4

    # --- Cost endpoint is leader-only and always answers -------------------
    cost = (
        await client.get(
            f"/api/v1/meetings/{meeting_id}/cost", headers=_auth(leader_token)
        )
    ).json()
    assert "estimated_usd" in cost


async def test_transcript_import_end_to_end(client: AsyncClient):
    token, _ = await _register(client, "importer")

    transcript_text = (
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\n"
        "Alice: Vendor review kickoff — quotes are in.\n"
        "Bob: Beacon came in twelve percent under budget.\n"
        "Alice: Then Beacon it is, decided.\n"
    )
    resp = await client.post(
        "/api/v1/meetings/import-transcript",
        headers=_auth(token),
        json={
            "transcript_text": transcript_text,
            "title": "E2E Imported Meeting",
            "meeting_type": "Vendor / Partner Review",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["utterance_count"] == 3
    assert body["status"] == "completed"

    detail = (
        await client.get(f"/api/v1/meetings/{body['id']}", headers=_auth(token))
    ).json()
    assert detail["status"] == "completed"
    assert detail["meeting_type"] == "Vendor / Partner Review"
    speakers = {u["speaker"] for u in detail["transcript"]["utterances"]}
    assert speakers == {"Alice", "Bob"}
