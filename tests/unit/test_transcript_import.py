"""Unit tests for transcript parsing (Upload Transcript setup mode)."""

from apps.api.services.meeting.meeting_service import MeetingService

parse = MeetingService.parse_transcript_text


def test_parses_speaker_lines():
    text = "Alice: Let's review pricing.\nBob: The vendor quote came in high."
    result = parse(text)
    assert result == [
        {"speaker": "Alice", "text": "Let's review pricing."},
        {"speaker": "Bob", "text": "The vendor quote came in high."},
    ]


def test_strips_vtt_headers_and_timestamps():
    text = (
        "WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\n"
        "Alice: We should ship in June.\n\n2\n"
        "00:00:05.000 --> 00:00:08.000\nBob: Agreed, June works.\n"
    )
    result = parse(text)
    assert result == [
        {"speaker": "Alice", "text": "We should ship in June."},
        {"speaker": "Bob", "text": "Agreed, June works."},
    ]


def test_strips_leading_bracket_timestamps():
    text = "[00:12:34] Alice: Budget looks fine.\n(45:10) Bob: I'll confirm."
    result = parse(text)
    assert result[0] == {"speaker": "Alice", "text": "Budget looks fine."}
    assert result[1] == {"speaker": "Bob", "text": "I'll confirm."}


def test_bare_lines_continue_previous_utterance():
    text = "Alice: This quarter was strong.\nRevenue grew twelve percent."
    result = parse(text)
    assert len(result) == 1
    assert result[0]["text"] == "This quarter was strong. Revenue grew twelve percent."


def test_bare_text_without_any_speaker_gets_default():
    result = parse("Just a raw note without attribution.")
    assert result == [
        {"speaker": "Speaker", "text": "Just a raw note without attribution."}
    ]


def test_empty_input_returns_nothing():
    assert parse("") == []
    assert parse("\n\nWEBVTT\n1\n") == []
