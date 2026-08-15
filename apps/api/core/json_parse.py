"""
Tolerant JSON extraction from LLM output.

Agents ask models to "respond ONLY with JSON" and then call ``json.loads`` on
whatever comes back. GPT-4o class models comply closely enough that this works
almost always. Smaller and open-weight models do not: they wrap the payload in
markdown fences, prepend "Here is the JSON:", append an explanatory paragraph,
or emit ``True``/``None`` where JSON wants ``true``/``null``.

That difference stops being academic the moment a fallback provider is in play.
A research pipeline that dies with ``Expecting value: line 4 column 18`` has not
found a bad answer — it has thrown away a good one over formatting.

This module extracts the JSON value from a noisy response and repairs the
handful of deviations that are unambiguous. It deliberately does NOT try to
salvage genuinely malformed structure: if the braces don't balance, the model
failed and the caller should see that, not receive a half-parsed object that
silently drops fields.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Distinguishes "no default supplied" from "default is None", since None is a
# legitimate thing for a caller to want back.
_sentinel = object()

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)

# Python literals that models leak into "JSON" output. Word-bounded and applied
# only outside string literals, so a chat log containing the word "None" is not
# rewritten.
_PY_LITERALS = ((r"\bTrue\b", "true"), (r"\bFalse\b", "false"), (r"\bNone\b", "null"))

# Markdown emphasis leaking into key position: models trained heavily on
# markdown sometimes emit ``**rationale**: "..."`` inside an otherwise valid
# object. Observed from gpt-oss:120b on a plain "respond with JSON" prompt.
# Safe to repair because a bolded bare word immediately before ``:`` cannot be
# anything but a key that lost its quotes.
_MD_KEY_RE = re.compile(r"(^|[\{\[,]\s*)\*\*([A-Za-z_][\w \-]*)\*\*\s*:", re.MULTILINE)

# Bare unquoted key: ``rationale: "..."`` at a position where a key belongs.
# \x00 matches a masked string literal (see _mask_strings).
_BARE_KEY_RE = re.compile(
    r"(^|[\{,]\s*)([A-Za-z_][\w\-]*)\s*:(?=\s*[\x00\[\{\d\-tfn])", re.MULTILINE
)

# A complete JSON string literal, escapes included.
_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
_MASK_RE = re.compile("\x00(\\d+)\x00")


def _mask_strings(text: str) -> tuple[str, list]:
    """Replace string literals with placeholders.

    Repairs then operate on structure only, with no risk of rewriting prose
    inside a value — and, unlike a chunk-by-chunk scan, a pattern can still
    look ahead past a string to the token after it.
    """
    parts: list = []

    def repl(m: "re.Match") -> str:
        parts.append(m.group(0))
        return f"\x00{len(parts) - 1}\x00"

    return _STR_RE.sub(repl, text), parts


def _unmask(text: str, parts: list) -> str:
    return _MASK_RE.sub(lambda m: parts[int(m.group(1))], text)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    # An unterminated fence — common when a response is truncated by max_tokens.
    if text.lstrip().startswith("```"):
        body = text.lstrip()[3:]
        if body[:4].lower().startswith("json"):
            body = body[4:]
        return body.rsplit("```", 1)[0].strip()
    return text.strip()


def _find_balanced(text: str) -> Optional[str]:
    """Return the first complete JSON object/array in ``text``.

    Scans with a depth counter while tracking string state, so braces inside
    string values don't confuse the match. This is what lets a payload survive
    trailing commentary, which is the most common way a small model breaks an
    otherwise-valid response.
    """
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _strip_trailing_commas(text: str) -> str:
    """Remove ``,`` before a closing brace/bracket, outside of strings."""
    masked, parts = _mask_strings(text)
    masked = re.sub(r",(\s*[}\]])", r"\1", masked)
    return _unmask(masked, parts)


def _fix_keys(text: str) -> str:
    """Restore quotes on keys the model emitted unquoted or markdown-bolded.

    Structure-only: string contents are masked first, so prose inside a value
    that happens to contain ``word:`` is never rewritten.
    """
    masked, parts = _mask_strings(text)
    masked = _MD_KEY_RE.sub(r'\1"\2":', masked)
    masked = _BARE_KEY_RE.sub(r'\1"\2":', masked)
    return _unmask(masked, parts)


def _fix_py_literals(text: str) -> str:
    """Convert Python's True/False/None to JSON's true/false/null."""
    masked, parts = _mask_strings(text)
    for pattern, repl in _PY_LITERALS:
        masked = re.sub(pattern, repl, masked)
    return _unmask(masked, parts)


def loads(text: Optional[str], default: Any = _sentinel) -> Any:
    """Parse JSON from a model response, tolerating common formatting noise.

    Tries progressively more forgiving strategies and stops at the first that
    yields valid JSON. Raises ``json.JSONDecodeError`` if none do — unless
    ``default`` is supplied, in which case it is returned instead.
    """
    if not text or not text.strip():
        if default is not _sentinel:
            return default
        raise json.JSONDecodeError("empty response", text or "", 0)

    raw = text.strip()
    candidates = []

    stripped = _strip_fences(raw)
    candidates.append(stripped)
    if stripped != raw:
        candidates.append(raw)

    balanced = _find_balanced(stripped)
    if balanced and balanced != stripped:
        candidates.append(balanced)

    # Repair passes, applied to the most promising candidate first. The
    # all-repairs variant comes last so a response that only needed one fix
    # isn't put through transforms it didn't need.
    for base in list(candidates):
        candidates.append(_strip_trailing_commas(base))
        candidates.append(_fix_keys(base))
        candidates.append(_fix_py_literals(base))
        candidates.append(_fix_keys(_fix_py_literals(_strip_trailing_commas(base))))

    seen = set()
    for candidate in candidates:
        c = candidate.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        try:
            return json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue

    preview = raw[:300].replace("\n", "\\n")
    logger.warning("Could not parse JSON from model response: %s", preview)
    if default is not _sentinel:
        return default
    raise json.JSONDecodeError("no valid JSON found in model response", raw, 0)


def loads_array(text: Optional[str], default: Any = _sentinel) -> Any:
    """Parse a response that should be a JSON *array*, unwrapping if needed.

    Ollama's constrained-decoding mode can only emit an object, so a prompt
    asking for ``[...]`` comes back as ``{"topics": [...]}``. The wrapper key is
    whatever the model chose, so this unwraps any single-key object whose value
    is a list rather than looking for a fixed name.

    Also unwraps a lone list found under a multi-key object, since models
    sometimes add a stray ``"count"`` or ``"summary"`` alongside the payload.
    """
    parsed = loads(text, default)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        lists = [v for v in parsed.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
        if not lists and default is not _sentinel:
            return default
    return parsed
