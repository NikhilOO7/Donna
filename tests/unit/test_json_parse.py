"""
Tests for tolerant JSON extraction from model output.

These cases are the real failure shapes seen when a fallback model serves a
prompt written for GPT-4o. The research pipeline died with
``Expecting value: line 4 column 18 (char 75)`` on output of exactly this kind.
"""

import json

import pytest

from apps.api.core import json_parse


def test_plain_json_object():
    assert json_parse.loads('{"a": 1}') == {"a": 1}


def test_plain_json_array():
    assert json_parse.loads('[{"topic": "x"}]') == [{"topic": "x"}]


def test_markdown_fenced():
    assert json_parse.loads('```json\n{"a": 1}\n```') == {"a": 1}


def test_bare_fence_without_language():
    assert json_parse.loads("```\n[1, 2, 3]\n```") == [1, 2, 3]


def test_unterminated_fence_from_truncation():
    """max_tokens cuts the closing fence off. The payload is still complete."""
    assert json_parse.loads('```json\n{"a": 1}') == {"a": 1}


def test_preamble_prose():
    text = 'Here is the JSON you requested:\n\n{"topic": "vendor pricing"}'
    assert json_parse.loads(text) == {"topic": "vendor pricing"}


def test_trailing_commentary():
    text = '[{"topic": "renewal"}]\n\nLet me know if you need more detail!'
    assert json_parse.loads(text) == [{"topic": "renewal"}]


def test_prose_on_both_sides():
    text = 'Sure! Here you go:\n```json\n{"ok": true}\n```\nHope that helps.'
    assert json_parse.loads(text) == {"ok": True}


def test_trailing_comma():
    assert json_parse.loads('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_trailing_comma_in_array():
    assert json_parse.loads("[1, 2, 3,]") == [1, 2, 3]


def test_python_literals():
    out = json_parse.loads('{"ok": True, "bad": False, "missing": None}')
    assert out == {"ok": True, "bad": False, "missing": None}


def test_braces_inside_strings_do_not_break_matching():
    """The balanced-scan must ignore braces that live inside string values."""
    text = 'Note:\n{"quote": "he said {this} and [that]", "n": 1}\nDone.'
    assert json_parse.loads(text) == {"quote": "he said {this} and [that]", "n": 1}


def test_escaped_quotes_inside_strings():
    text = '{"quote": "she said \\"yes\\" clearly"}'
    assert json_parse.loads(text) == {"quote": 'she said "yes" clearly'}


def test_literal_words_inside_strings_are_not_rewritten():
    """'None' as prose must survive; only bare literals get converted."""
    out = json_parse.loads('{"note": "None of the vendors replied", "x": None}')
    assert out["note"] == "None of the vendors replied"
    assert out["x"] is None


def test_nested_structure_survives():
    text = '```json\n{"topics": [{"t": "a", "q": ["x", "y"]}], "n": 1}\n```'
    assert json_parse.loads(text) == {"topics": [{"t": "a", "q": ["x", "y"]}], "n": 1}


def test_default_returned_on_garbage():
    assert json_parse.loads("I cannot help with that.", {}) == {}


def test_default_none_is_honoured():
    """A None default must be returned, not treated as 'no default given'."""
    assert json_parse.loads("nonsense", None) is None


def test_raises_without_default():
    with pytest.raises(json.JSONDecodeError):
        json_parse.loads("I cannot help with that.")


def test_empty_input():
    assert json_parse.loads("", []) == []
    assert json_parse.loads(None, []) == []
    with pytest.raises(json.JSONDecodeError):
        json_parse.loads("")


def test_genuinely_broken_structure_still_fails():
    """Unbalanced braces mean the model failed. Don't invent a result.

    Half-parsing this would silently drop fields, which is worse than an error
    the caller can see and retry.
    """
    with pytest.raises(json.JSONDecodeError):
        json_parse.loads('{"a": 1, "b": ')


# --------------------------------------------------------------------------
# loads_array — Ollama's JSON mode can only emit objects
# --------------------------------------------------------------------------


def test_array_passes_through():
    assert json_parse.loads_array('[{"topic": "a"}]') == [{"topic": "a"}]


def test_unwraps_single_key_object():
    """Constrained decoding wraps a requested array in an object.

    The wrapper key is whatever the model picked, so unwrapping keys off
    "single key whose value is a list", not a fixed name.
    """
    assert json_parse.loads_array('{"topics": [{"t": "a"}]}') == [{"t": "a"}]
    assert json_parse.loads_array('{"items": [1, 2]}') == [1, 2]
    assert json_parse.loads_array('{"results": []}') == []


def test_unwraps_lone_list_among_scalars():
    text = '{"count": 2, "topics": [{"t": "a"}, {"t": "b"}]}'
    assert json_parse.loads_array(text) == [{"t": "a"}, {"t": "b"}]


def test_ambiguous_multi_list_object_is_not_guessed():
    """Two lists means we cannot know which is the payload — don't invent one."""
    out = json_parse.loads_array('{"a": [1], "b": [2]}')
    assert isinstance(out, dict)


def test_array_default_on_garbage():
    assert json_parse.loads_array("sorry, I can't", []) == []


def test_fenced_wrapped_array():
    assert json_parse.loads_array('```json\n{"topics": [{"t": "a"}]}\n```') == [
        {"t": "a"}
    ]


# --------------------------------------------------------------------------
# Real failure shapes captured from live models
# --------------------------------------------------------------------------


def test_gpt_oss_markdown_bolded_key():
    """Captured from gpt-oss:120b on this repo's own research prompt.

    It emitted `**rationale**:` instead of `"rationale":` — markdown emphasis
    leaking into key position. Unambiguous, so it is repaired.
    """
    text = """{
  "topics": [
    {
      "topic": "Contract negotiation points",
      **rationale**: "Identifies key clauses - SLAs, exit terms, IP ownership.",
      "search_queries": ["SaaS contract negotiation checklist"]
    }
  ]
}"""
    out = json_parse.loads_array(text)
    assert len(out) == 1
    assert out[0]["rationale"].startswith("Identifies key clauses")
    assert out[0]["topic"] == "Contract negotiation points"


def test_bare_unquoted_key():
    text = '{"topic": "a", rationale: "because"}'
    assert json_parse.loads(text) == {"topic": "a", "rationale": "because"}


def test_colon_inside_prose_value_is_not_treated_as_a_key():
    """A value containing 'word:' must not be rewritten into a key."""
    text = '{"note": "Decision: proceed with Acme", "n": 1}'
    assert json_parse.loads(text) == {"note": "Decision: proceed with Acme", "n": 1}


def test_unquoted_value_is_not_guessed():
    """Captured from llama3.2:3b without constrained decoding.

    An unquoted value spanning commas and periods cannot be delimited
    unambiguously, so this must fail rather than invent a parse. The real fix
    is `response_format={"type":"json_object"}`, which llm_provider applies to
    Ollama automatically — see _force_json_mode.
    """
    text = """[
  {
    "topic": "Acme market share",
    "rationale": This will help us understand Acme's position, strengths, weaknesses.
    "search_queries": ["Acme market share"]
  }
]"""
    assert json_parse.loads(text, None) is None
