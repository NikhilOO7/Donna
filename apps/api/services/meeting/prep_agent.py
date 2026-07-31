"""
Meeting Prep Agent.

Converts a user's free-text (or spoken) description of an upcoming meeting
into structured, contextual prep — the product's original "You are Donna,
a proactive meeting collaborator" contract:

    {role, meeting_type, meeting_goal, agenda_items,
     risks_or_tensions, confidence_notes}

Used by the Smart Fill button and the Conversational Setup flow. In
conversational mode, the previous JSON is passed back with each new user
message so the prep refines incrementally.
"""

import json
import logging
from typing import Any, Dict, Optional

from openai import AsyncOpenAI

from apps.api.core.config import settings
from apps.api.core.resilience import resilient_call

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Donna, a proactive meeting collaborator. Your job is to convert user voice/text input into smart, contextual prep for an upcoming meeting.

Input will include:
- A few spoken/text lines from the user
- Optionally, their job title or function
- Hints about the meeting type or purpose
- Optionally, the prep JSON you produced earlier in this conversation (refine it with the new input rather than starting over)

Your output must be structured JSON with:
{
"role": string, // if unclear, infer likely role from domain language
"meeting_type": string, // e.g. Design Sync, Product Review, Strategy Planning
"meeting_goal": string, // clear, 1-line goal that shows intent
"agenda_items": [string], // 2-4 bullet items that should be covered
"risks_or_tensions": [string], // optional: inferred challenges or tensions to address
"confidence_notes": string // short comment on what was inferred vs. stated directly
}

Here are examples of input → output pairs:

Input:
"I'm prepping for a session tomorrow with the engineers to make sure we can ship the component on time. I'm in product design."

Output:
{
"role": "Product Designer",
"meeting_type": "Engineering Sync",
"meeting_goal": "Ensure component is ready for on-time delivery",
"agenda_items": [
"Review latest component handoff",
"Discuss open engineering blockers",
"Align on timeline and delivery risks"
],
"risks_or_tensions": ["Potential delay in handoff causing timeline slip"],
"confidence_notes": "Role and meeting type inferred with high confidence from keywords"
}

Input:
"I'm leading a go-to-market check-in with ops and brand to finalize messaging. Deadline's next week."

Output:
{
"role": "Product Marketing Manager",
"meeting_type": "Go-to-Market Planning",
"meeting_goal": "Finalize GTM messaging and cross-functional readiness",
"agenda_items": [
"Review updated messaging framework",
"Get input from ops and brand",
"Confirm asset deadlines"
],
"risks_or_tensions": ["Misalignment between brand and ops timelines"],
"confidence_notes": "Role inferred from GTM reference and language"
}

Respond ONLY with the JSON object."""


class PrepAgent:
    """Structured meeting prep from free-form input (Smart Fill + conversational setup)."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    @resilient_call("openai", max_retries=2, timeout_seconds=20)
    async def generate(
        self,
        user_input: str,
        current: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Produce (or refine) the structured prep JSON."""
        user_parts = []
        if current:
            user_parts.append(
                "Prep so far (refine this with my new input):\n"
                + json.dumps(current, indent=2)
            )
        user_parts.append(f'New input:\n"{user_input}"')

        response = await self.client.chat.completions.create(
            model=settings.model_fast,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(user_parts)},
            ],
            temperature=0.3,
            max_tokens=600,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(content)
        return self._normalize(result)

    @staticmethod
    def _normalize(result: Dict[str, Any]) -> Dict[str, Any]:
        """Coerce the LLM output into the exact contract shape."""

        def _str(v: Any) -> str:
            return str(v).strip() if v is not None else ""

        def _str_list(v: Any, cap: int) -> list:
            if not isinstance(v, list):
                return []
            return [str(x).strip() for x in v if str(x).strip()][:cap]

        return {
            "role": _str(result.get("role"))[:120],
            "meeting_type": _str(result.get("meeting_type"))[:120],
            "meeting_goal": _str(result.get("meeting_goal"))[:300],
            "agenda_items": _str_list(result.get("agenda_items"), 6),
            "risks_or_tensions": _str_list(result.get("risks_or_tensions"), 4),
            "confidence_notes": _str(result.get("confidence_notes"))[:300],
        }


prep_agent = PrepAgent()
