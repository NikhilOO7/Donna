"""
Reply Agent — answers when someone actually talks to Donna.

Every other live agent is an observer: it watches the discussion and offers
context the room didn't ask for. That is the right default, because a
collaborator who interjects constantly is worse than one who stays quiet.

But it leaves a hole that anyone testing the product falls straight into.
"Donna, can you hear me?" is not meeting content, so the observer agents
correctly produce nothing — and to the person speaking, a system that answers
nothing when addressed by name is indistinguishable from a broken one. The
first thing anyone says to a voice assistant is a direct question, and that was
the one input guaranteed to produce silence.

This agent handles exactly that case: someone addresses Donna, so Donna
answers. It is deliberately narrow —

  * It fires only on direct address, never on ambient discussion. The other
    agents own that territory and duplicating them would double every nudge.
  * It answers from meeting context (documents, research, transcript) and says
    plainly when it doesn't know, rather than inventing something that sounds
    right — a confident wrong answer spoken aloud in a real meeting is far more
    damaging than an admission of ignorance.
  * It answers in one or two sentences. This text is going to be read aloud
    into a room of people who are mid-conversation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from apps.api.core import llm_provider
from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

# How far back to look for an address.
#
# Two utterances is the intuitive choice and it is wrong. Dispatch cycles
# coalesce — a burst of speech runs ONE cycle, not one per utterance — so by
# the time the cycle executes, the conversation has usually moved a few turns
# past the question. With a window of 2, asking Donna something and then
# continuing to talk (which is what people actually do) silently dropped the
# question.
#
# A wider window is only safe because replies dedupe on the question itself:
# re-examining an utterance that was already answered produces the same
# fingerprint and is suppressed, so widening this cannot cause repeat answers.
_LOOKBACK = 6

# Addressed by name. Tolerates the mishearings Deepgram actually produces on
# "Donna" so a mis-transcribed name doesn't silently drop the question.
# "donald" is not hypothetical — it is what live transcription returned, and
# an assistant whose own name is misheard is unreachable by voice.
_NAME_RE = re.compile(
    r"\b(donna|dona|donnna|dawna|donner|donald|donuts?|tanna)\b", re.IGNORECASE
)

# Generic assistant address that doesn't use the name.
_ADDRESS_RE = re.compile(
    r"\b("
    r"can you hear me|are you there|are you listening|do you hear me|"
    r"am i audible|can you respond|you there|hey there"
    r")\b",
    re.IGNORECASE,
)

# A leading vocative: "Donna," / "Hey Donna" / "OK Donna, ...". Stripped
# before testing for a question, because the thing being asked comes *after*
# the name — "Donna, can you remind me" is a request, and anchoring the
# question word to the start of the raw string would miss all of them.
_VOCATIVE_RE = re.compile(
    r"^\s*(?:(?:hi|hey|hello|ok|okay|so|um|uh|excuse me)[\s,]+)*"
    r"(?:donna|dona|donnna|dawna|donner|donald|donuts?|tanna)\b[\s,.:!-]*",
    re.IGNORECASE,
)

# The trailing \b is load-bearing. Without it "do" matches the first two
# letters of "Donna", so every sentence merely *mentioning* her name reads as
# a question aimed at her — and she interrupts the room each time someone
# refers to her in passing.
_QUESTION_RE = re.compile(
    r"(\?|^\s*(what|who|when|where|why|how|which|can|could|would|should|"
    r"is|are|do|does|did|will|tell me|remind me|show me|give me|"
    r"find|check|look up|pull up|summarize|explain)\b)",
    re.IGNORECASE,
)

_MAX_SPOKEN_CHARS = 320


def _addressed(text: str) -> bool:
    """Is this utterance aimed at Donna, rather than at the room?

    The distinction that matters is vocative versus reference. "Donna, what did
    Acme quote?" is a question to her; "Donna flagged that earlier" is one
    colleague telling another what she did. Answering the second out loud is
    how an assistant becomes something people mute, so the name alone is never
    sufficient — it has to be followed by something being asked.
    """
    if not text or not text.strip():
        return False

    if _ADDRESS_RE.search(text):
        return True

    vocative = _VOCATIVE_RE.match(text)
    if not vocative:
        return False

    # What's left after "Donna," is the actual request.
    remainder = text[vocative.end() :].strip()
    if not remainder:
        return True  # just her name, said alone — she should acknowledge
    return bool(_QUESTION_RE.search(remainder))


def _merge_turns(utterances: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Join consecutive utterances from the same speaker into one turn.

    Speech-to-text emits sentence *fragments*, not thoughts. Reconstructing
    the turn is what lets a question survive being chopped in three.
    """
    turns: List[Dict[str, str]] = []
    for u in utterances:
        speaker = str(u.get("speaker") or "someone")
        text = str(u.get("text") or "").strip()
        if not text:
            continue
        if turns and turns[-1]["speaker"] == speaker:
            turns[-1]["text"] = f"{turns[-1]['text']} {text}".strip()
        else:
            turns.append({"speaker": speaker, "text": text})
    return turns


class ReplyAgent:
    """Answers direct address, briefly, for speaking aloud."""

    async def analyze(
        self,
        utterances: List[Dict[str, Any]],
        meeting_id: str,
        owner_id: Optional[str] = None,
        attached_doc_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not utterances:
            return None

        # Merge consecutive fragments from the same speaker before testing.
        #
        # Deepgram finalizes on short pauses, so one spoken sentence commonly
        # arrives as several utterances:
        #
        #     "Donna,"  /  "what did we decide about"  /  "Acme?"
        #
        # Tested individually, none of those is a question addressed to Donna:
        # the name is in the first, the verb in the second, the object in the
        # third. Merging reconstructs the actual turn.
        turns = _merge_turns(utterances[-_LOOKBACK:])
        addressed = [t for t in turns if _addressed(t["text"])]
        if not addressed:
            return None

        question = addressed[-1]["text"].strip()
        speaker = addressed[-1]["speaker"]

        context = await self._gather_context(
            question, owner_id=owner_id, attached_doc_ids=attached_doc_ids
        )

        try:
            answer = await self._answer(
                question=question,
                speaker=speaker,
                context=context,
                transcript=utterances[-8:],
            )
        except Exception as e:
            logger.warning(f"[Reply] answer failed: {e}")
            return None

        if not answer:
            return None

        answer = answer.strip()[:_MAX_SPOKEN_CHARS]
        logger.info(f"[Reply] answering {speaker}: {question[:60]}")

        return {
            "nudge_type": "reply",
            "title": f"Answering {speaker}"[:120],
            "content": answer,
            "source_agent": "reply_agent",
            "source_data": {
                "question": question[:500],
                "asked_by": speaker,
                "grounded": bool(context),
                # Consumed by the dispatcher's speak path — this nudge exists
                # to be heard, not read.
                "speak": True,
                # Dedupe on the QUESTION, not the answer. The answer is
                # LLM-generated and comes out worded differently on each
                # dispatch cycle, so hashing it lets one question produce two
                # near-identical spoken replies.
                "dedupe_key": f"{speaker}|{question}"[:500],
            },
            # A direct question is always relevant to the person who asked it.
            "relevance_score": 0.95,
        }

    async def _gather_context(
        self,
        question: str,
        owner_id: Optional[str],
        attached_doc_ids: Optional[List[str]],
    ) -> str:
        """Retrieve supporting passages. Best-effort — silence beats a stall."""
        try:
            from apps.api.services.document.contextual_processor import (
                ContextualEmbeddingGenerator,
            )
            from apps.api.services.document.vector_store import ModernVectorStore

            embedding = (
                await ContextualEmbeddingGenerator().generate_contextual_embedding(
                    text=question, context_level="local"
                )
            )
            filters: Dict[str, Any] = {}
            if owner_id:
                filters["owner_id"] = str(owner_id)
            results = await ModernVectorStore().search_with_context(
                query_embedding=embedding,
                context_level="unified",
                top_k=4,
                filters=filters or None,
            )
            passages = [r.content for r in results if getattr(r, "content", None)]
            return "\n---\n".join(p[:600] for p in passages[:4])
        except Exception as e:
            logger.debug(f"[Reply] context retrieval skipped: {e}")
            return ""

    @resilient_call("openai", max_retries=1, timeout_seconds=15)
    async def _answer(
        self,
        question: str,
        speaker: str,
        context: str,
        transcript: List[Dict[str, Any]],
    ) -> Optional[str]:
        recent = "\n".join(
            f"{u.get('speaker', 'Speaker')}: {u.get('text', '')}" for u in transcript
        )[:2000]

        client = llm_provider.failover_client()
        response = await client.chat.completions.create(
            model=settings.model_fast,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Donna, an AI collaborator sitting in on a live "
                        "meeting. Someone has just spoken to you directly. Answer "
                        "them out loud.\n\n"
                        "Rules:\n"
                        "- ONE or TWO sentences. This is read aloud into a live "
                        "room; long answers are an interruption.\n"
                        "- Use the provided context when it answers the question, "
                        "and say which document or figure it came from.\n"
                        "- If the context does not answer it, say so plainly and "
                        "briefly. Never invent a number, name, or date.\n"
                        "- If they are only checking whether you can hear them, "
                        "confirm warmly in one short sentence.\n"
                        "- Speak naturally. No markdown, no bullet points, no "
                        "preamble like 'Great question'."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Recent conversation:\n{recent}\n\n"
                        f"Context from the team's documents and data:\n"
                        f"{context or '(nothing relevant found)'}\n\n"
                        f'{speaker} said to you: "{question}"\n\n'
                        f"Your spoken reply:"
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=160,
        )
        return (response.choices[0].message.content or "").strip() or None


reply_agent = ReplyAgent()
