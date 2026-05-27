"""
Email Service.

Sends meeting summaries via Postmark. Gracefully degrades if
Postmark API key is not configured. The HTML body is rendered from
the Jinja2 template at ``templates/meeting_summary.html``.
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "meeting_summary.html"


@lru_cache(maxsize=1)
def _get_template_env():
    """Build (once) a Jinja2 environment for the templates dir."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )


class EmailService:
    """Send meeting summary emails via Postmark."""

    def _get_client(self):
        if not settings.postmark_api_key:
            return None
        try:
            from postmarker.core import PostmarkClient

            return PostmarkClient(server_token=settings.postmark_api_key)
        except Exception as e:
            logger.warning(f"Postmark client init failed: {e}")
            return None

    async def send_summary_email(
        self,
        recipients: List[str],
        meeting_title: str,
        summary: Dict[str, Any],
    ) -> Optional[str]:
        """Send meeting summary email to attendees.

        Returns:
            Postmark message ID if sent, None if skipped/failed.
        """
        if not recipients:
            logger.warning("No recipients for summary email")
            return None

        client = self._get_client()
        if not client:
            logger.info(
                f"Postmark not configured — would send to {len(recipients)} "
                f"recipients: {', '.join(recipients)}"
            )
            return "MOCK_NO_POSTMARK_KEY"

        html_body = self._render_html(meeting_title, summary)

        try:
            response = client.emails.send(
                From=settings.postmark_from_email,
                To=", ".join(recipients),
                Subject=f"Meeting Summary: {meeting_title}",
                HtmlBody=html_body,
                MessageStream="outbound",
            )
            message_id = response.get("MessageID", "")
            logger.info(
                f"Summary email sent to {len(recipients)} recipients. "
                f"MessageID: {message_id}"
            )
            return message_id
        except Exception as e:
            logger.error(f"Postmark send failed: {e}")
            return None

    def _render_html(self, title: str, summary: Dict[str, Any]) -> str:
        """Render the responsive HTML email from the Jinja2 template.

        Falls back to a minimal inline body if the template can't be
        loaded for any reason (so email delivery never hard-fails on a
        templating issue).
        """
        context = {
            "title": title,
            "exec_summary": summary.get(
                "executive_summary", "No summary available."
            ),
            "decisions": summary.get("decisions_summary", []) or [],
            "actions": summary.get("action_items", []) or [],
            "insights": summary.get("ai_insights_used", []) or [],
            "follow_ups": summary.get("follow_up_recommendations", []) or [],
        }
        try:
            template = _get_template_env().get_template(_TEMPLATE_NAME)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Email template render failed, using fallback: {e}")
            return (
                f"<html><body><h1>{title}</h1>"
                f"<p>{context['exec_summary']}</p></body></html>"
            )


email_service = EmailService()
