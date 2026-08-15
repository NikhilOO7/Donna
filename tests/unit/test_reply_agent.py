"""
Tests for direct-address detection and nudge deduplication.

Both exist because of the same failure: the live agents are observers, so a
person testing the product ("Donna, can you hear me?") got silence, while a
finding that stayed relevant got repeated on every dispatch cycle until the
panel was nine cards saying two things.
"""

from unittest.mock import patch

from apps.api.services.meeting.reply_agent import _addressed


class TestDirectAddress:
    """What counts as talking TO Donna, versus talking about her."""

    def test_mic_checks_are_addressed(self):
        # The literal first thing anyone says to a voice assistant.
        for text in (
            "Can you hear me?",
            "Am I audible to you?",
            "Are you there?",
            "Can you respond me?",
            "Hi Donna, are you listening?",
        ):
            assert _addressed(text) is True, text

    def test_questions_by_name_are_addressed(self):
        for text in (
            "Donna, what did Acme quote us?",
            "Donna can you remind me of the renewal date",
            "Hey Donna, show me the security findings",
        ):
            assert _addressed(text) is True, text

    def test_talking_about_donna_is_not_addressing_her(self):
        """The distinction that keeps her from interrupting the room.

        Mentioning her name in passing must not trigger a spoken reply — that
        is how an assistant becomes something people mute.
        """
        for text in (
            "Donna flagged the region mismatch earlier and I think she was right",
            "We should check whether Donna already pulled the vendor numbers "
            "before we go asking the vendor directly",
        ):
            assert _addressed(text) is False, text

    def test_ordinary_discussion_is_not_addressed(self):
        for text in (
            "Acme quoted us 185 thousand annually with 42 millisecond latency.",
            "I think Beacon is cheaper, so let's go with Beacon.",
            "What's the renewal price?",  # a question, but to the room
            "",
        ):
            assert _addressed(text) is False, text

    def test_tolerates_transcription_errors_on_the_name(self):
        """Deepgram mishears 'Donna'. A misheard name shouldn't eat the question."""
        for text in ("Dona, what did we agree?", "Dawna can you check that?"):
            assert _addressed(text) is True, text


class TestNudgeFingerprint:
    """Identity of what a nudge says, for suppressing repeats."""

    def test_same_content_same_fingerprint(self):
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        assert fp("context", "Acme covers only 3 regions.") == fp(
            "context", "Acme covers only 3 regions."
        )

    def test_whitespace_and_case_do_not_change_identity(self):
        """Scores drift between cycles; the text is what identifies a finding."""
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        assert fp("context", "Acme covers  only 3 regions.") == fp(
            "context", "acme covers only 3 regions."
        )
        assert fp("context", "  Acme covers only 3 regions.  ") == fp(
            "context", "Acme covers only 3 regions."
        )

    def test_different_content_differs(self):
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        assert fp("context", "Acme covers 3 regions.") != fp(
            "context", "Beacon costs $240,000."
        )

    def test_same_text_from_a_different_agent_is_distinct(self):
        """A fact-check and a context card saying the same thing are not the
        same event — one is a verification, the other a retrieval."""
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        assert fp("context", "Acme covers 3 regions.") != fp(
            "fact_check", "Acme covers 3 regions."
        )


class TestSpeakGating:
    """When Donna is allowed to interrupt a room."""

    def test_reply_bypasses_relevance_and_cooldown(self):
        from apps.api.services.meeting import agent_dispatcher as d

        assert "reply" in d._SPEAK_ALWAYS_TYPES
        # Not in the scored set: a reply is never suppressed for scoring low,
        # because someone asked a question and is waiting for an answer.
        assert "reply" not in d._SPEAK_TYPES

    def test_observations_still_require_a_high_bar(self):
        from apps.api.services.meeting import agent_dispatcher as d

        assert d._SPEAK_MIN_RELEVANCE >= 0.8
        assert d._SPEAK_COOLDOWN_SECONDS >= 60

    def test_spoken_text_is_bounded(self):
        from apps.api.services.meeting import agent_dispatcher as d

        assert 0 < d._MAX_SPOKEN_CHARS <= 500


class TestReplyAgentBudget:
    def test_reply_budget_stretches_on_fallback(self):
        from apps.api.core import llm_provider as lp
        from apps.api.core.config import settings
        from apps.api.services.meeting.agent_dispatcher import (
            _AGENT_TIMEOUTS,
            _agent_timeout,
        )

        lp.reset_for_tests()
        try:
            assert _agent_timeout("reply") == _AGENT_TIMEOUTS["reply"]
            with patch.object(settings, "ollama_api_key", "k"):
                lp.note_failure(RuntimeError("insufficient_quota"))
                assert _agent_timeout("reply") > _AGENT_TIMEOUTS["reply"]
        finally:
            lp.reset_for_tests()


class TestDedupeKey:
    """Agents that know their own identity can override the text hash."""

    def test_dedupe_key_beats_differing_content(self):
        """One question must not yield two replies.

        The answer is LLM-generated, so consecutive dispatch cycles word it
        differently and a content hash lets both through. Observed live: one
        question, two spoken replies saying the same thing.
        """
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        key = "Nikhil|Donna, what did Acme quote us?"
        assert fp(
            "reply", "Acme quoted $185,000 per year and covers 3 regions.", key
        ) == fp("reply", "Acme quoted us $185,000 annually across 3 regions.", key)

    def test_different_questions_stay_distinct(self):
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        assert fp("reply", "same answer", "Nikhil|what did Acme quote?") != fp(
            "reply", "same answer", "Nikhil|when does the contract renew?"
        )

    def test_absent_key_falls_back_to_content(self):
        from apps.api.services.meeting.meeting_service import MeetingService

        fp = MeetingService._nudge_fingerprint
        assert fp("context", "Acme covers 3 regions.") == fp(
            "context", "Acme covers 3 regions.", None
        )


class TestLookbackWindow:
    def test_window_survives_coalesced_bursts(self):
        """Dispatch coalesces, so the question is rarely the last utterance.

        A burst of speech runs one cycle, not one per utterance. With a
        two-utterance window, asking Donna something and then continuing to
        talk — which is what people actually do — dropped the question.
        """
        from apps.api.services.meeting.reply_agent import _LOOKBACK

        assert _LOOKBACK >= 5, (
            "too narrow: a question asked mid-burst is dropped when the "
            "conversation moves on before the cycle runs"
        )

    def test_window_stays_inside_the_dispatch_state_window(self):
        """get_dispatch_state ships only the last 12 utterances."""
        from apps.api.services.meeting.reply_agent import _LOOKBACK

        assert _LOOKBACK <= 12


class TestSpeakerAttribution:
    """A transcript is shared, so speaker labels must be absolute."""

    def _user(self, full_name=None, email=None):
        class U:
            pass

        u = U()
        u.full_name = full_name
        u.email = email
        return u

    def test_attendee_name_wins(self):
        from apps.api.routers.meetings import _display_name_for

        user = self._user(full_name="Nikhil Bindal", email="nikhil@gmail.com")
        attendees = [{"email": "nikhil@gmail.com", "name": "Nik"}]
        assert _display_name_for(attendees, user) == "Nik"

    def test_owner_absent_from_attendees_still_gets_a_name(self):
        """The bug: the meeting owner is usually not in their own attendee
        list, so my_name was null for the one person guaranteed to be there —
        and the client persisted the literal string "You" instead."""
        from apps.api.routers.meetings import _display_name_for

        user = self._user(full_name="Nikhil Bindal", email="nikhil@gmail.com")
        assert _display_name_for([], user) == "Nikhil Bindal"

    def test_falls_back_to_email_handle_not_a_pronoun(self):
        from apps.api.routers.meetings import _display_name_for

        user = self._user(full_name=None, email="nikhil@gmail.com")
        assert _display_name_for([], user) == "nikhil"

    def test_viewer_relative_labels_are_recognised(self):
        from apps.api.routers.meetings import _VIEWER_RELATIVE_SPEAKERS

        for label in ("you", "me", "myself", "speaker"):
            assert label in _VIEWER_RELATIVE_SPEAKERS

    def test_real_names_are_not_treated_as_placeholders(self):
        """Overriding a genuine name would break multi-speaker attribution."""
        from apps.api.routers.meetings import _VIEWER_RELATIVE_SPEAKERS

        for name in ("nikhil", "priya raman", "sarah chen", "donna"):
            assert name not in _VIEWER_RELATIVE_SPEAKERS


class TestReplyIsNotGatedOnTheNudgeFlag:
    """Answering when spoken to is not an interruption."""

    async def test_reply_speaks_even_with_voice_nudges_off(self):
        """The flag controls unsolicited interjections, not answers.

        Gating replies on it meant that with the (default-off) flag disabled,
        asking Donna a direct question produced silence — which reads as a
        broken product rather than a configured one.
        """
        from unittest.mock import AsyncMock, patch

        from apps.api.services.meeting import agent_dispatcher as d

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)  # flag OFF
        redis.set = AsyncMock(return_value=True)
        redis.publish = AsyncMock()

        with patch(
            "apps.api.core.connections.get_redis_client",
            AsyncMock(return_value=redis),
        ):
            await d._maybe_speak_nudge(
                "m1",
                {
                    "nudge_type": "reply",
                    "title": "Answering Nikhil",
                    "content": "Acme quoted $185,000 across 3 regions.",
                    "relevance_score": 0.95,
                },
            )

        redis.publish.assert_awaited()
        channel, payload = redis.publish.await_args.args
        assert channel == "meeting:m1:speak"
        # The card title would make her narrate her own UI.
        assert "Answering Nikhil" not in payload
        assert "185,000" in payload

    async def test_observation_stays_silent_with_the_flag_off(self):
        """Unsolicited nudges must still respect the setting."""
        from unittest.mock import AsyncMock, patch

        from apps.api.services.meeting import agent_dispatcher as d

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)  # flag OFF
        redis.publish = AsyncMock()

        with patch(
            "apps.api.core.connections.get_redis_client",
            AsyncMock(return_value=redis),
        ):
            await d._maybe_speak_nudge(
                "m1",
                {
                    "nudge_type": "fact_check",
                    "title": "Checking a claim",
                    "content": "Beacon is $240,000, not cheaper than Acme.",
                    "relevance_score": 0.95,
                },
            )

        redis.publish.assert_not_awaited()


class TestFragmentedSpeech:
    """Speech-to-text emits fragments, not sentences."""

    def test_question_split_across_utterances_is_reconstructed(self):
        """The exact shape live transcription produced.

        Deepgram finalized on every short pause, so one question arrived as
        three utterances. Individually none of them is a question addressed to
        Donna — the name is in the first, the verb in the second, the object in
        the third — so the reply agent saw nothing to answer.
        """
        from apps.api.services.meeting.reply_agent import _addressed, _merge_turns

        fragments = [
            {"speaker": "Nikhil Bindal", "text": "Donald,"},
            {"speaker": "Nikhil Bindal", "text": "we did what did we decide about"},
            {"speaker": "Nikhil Bindal", "text": "acne?"},
        ]
        # The two fragments carrying the actual question are unanswerable on
        # their own — the name is in neither.
        assert _addressed(fragments[1]["text"]) is False
        assert _addressed(fragments[2]["text"]) is False

        turns = _merge_turns(fragments)
        assert len(turns) == 1
        assert _addressed(turns[0]["text"]) is True
        # And the merged turn carries the QUESTION, not just the name — that is
        # what gets sent to the model to answer.
        assert "decide about" in turns[0]["text"]

    def test_different_speakers_are_not_merged(self):
        """Merging across speakers would attribute one person's words to another."""
        from apps.api.services.meeting.reply_agent import _merge_turns

        turns = _merge_turns(
            [
                {"speaker": "Nikhil", "text": "Donna,"},
                {"speaker": "Priya", "text": "what did we decide?"},
            ]
        )
        assert len(turns) == 2
        assert turns[0]["speaker"] == "Nikhil"

    def test_misheard_name_still_reaches_her(self):
        """'Donald' is what live STT returned for 'Donna'."""
        from apps.api.services.meeting.reply_agent import _addressed

        for text in (
            "Donald, what did we decide about Acme?",
            "Donuts, can you check the renewal date?",
        ):
            assert _addressed(text) is True, text

    def test_empty_fragments_are_dropped(self):
        from apps.api.services.meeting.reply_agent import _merge_turns

        turns = _merge_turns(
            [
                {"speaker": "Nikhil", "text": "  "},
                {"speaker": "Nikhil", "text": "Donna?"},
            ]
        )
        assert len(turns) == 1
        assert turns[0]["text"] == "Donna?"


class TestSttConfig:
    """Transcription settings the voice path depends on."""

    def test_endpointing_is_relaxed(self):
        """Deepgram's 10ms default chops sentences into fragments."""
        import re

        src = open("apps/workers/meeting_voice_worker.py").read()
        m = re.search(r"endpointing=(\d+)", src)
        assert m, "endpointing must be set explicitly"
        assert int(m.group(1)) >= 200

    def test_assistant_name_is_keyword_boosted(self):
        """Her own name is the token that must not be misheard."""
        from apps.workers.meeting_voice_worker import _DEFAULT_STT_KEYWORDS

        assert any(k.lower().startswith("donna") for k in _DEFAULT_STT_KEYWORDS)
