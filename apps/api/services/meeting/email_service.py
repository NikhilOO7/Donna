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

    def _send(
        self,
        recipients: List[str],
        subject: str,
        html_body: str,
        ics_attachment: Optional[str] = None,
        ics_name: str = "donna.ics",
    ) -> Optional[str]:
        """Shared Postmark send path with optional .ics attachment."""
        if not recipients:
            return None

        client = self._get_client()
        if not client:
            logger.info(
                f"Postmark not configured — would send '{subject}' to "
                f"{len(recipients)} recipients: {', '.join(recipients)}"
            )
            return "MOCK_NO_POSTMARK_KEY"

        kwargs: Dict[str, Any] = {
            "From": settings.postmark_from_email,
            "To": ", ".join(recipients),
            "Subject": subject,
            "HtmlBody": html_body,
            "MessageStream": "outbound",
        }
        if ics_attachment:
            import base64

            kwargs["Attachments"] = [
                {
                    "Name": ics_name,
                    "Content": base64.b64encode(ics_attachment.encode()).decode(),
                    "ContentType": "text/calendar; method=PUBLISH",
                }
            ]
        try:
            response = client.emails.send(**kwargs)
            message_id = response.get("MessageID", "")
            logger.info(
                f"Email '{subject}' sent to {len(recipients)} recipients. "
                f"MessageID: {message_id}"
            )
            return message_id
        except Exception as e:
            logger.error(f"Postmark send failed: {e}")
            return None

    async def send_summary_email(
        self,
        recipients: List[str],
        meeting_title: str,
        summary: Dict[str, Any],
        ics_attachment: Optional[str] = None,
    ) -> Optional[str]:
        """Send meeting summary email to attendees.

        Returns:
            Postmark message ID if sent, None if skipped/failed.
        """
        if not recipients:
            logger.warning("No recipients for summary email")
            return None
        return self._send(
            recipients,
            f"Meeting Summary: {meeting_title}",
            self._render_html(meeting_title, summary),
            ics_attachment=ics_attachment,
            ics_name="follow-ups.ics",
        )

    async def send_invite_email(
        self,
        recipients: List[str],
        meeting_title: str,
        meeting_url: str,
        scheduled_label: Optional[str] = None,
        agenda_titles: Optional[List[str]] = None,
        ics_attachment: Optional[str] = None,
    ) -> Optional[str]:
        """Invite attendees to a Donna meeting with a join link."""
        agenda_html = ""
        if agenda_titles:
            items = "".join(f"<li>{t}</li>" for t in agenda_titles[:8])
            agenda_html = f"<h3>Agenda</h3><ul>{items}</ul>"
        html = (
            f"<html><body style='font-family:sans-serif'>"
            f"<h2>You're invited: {meeting_title}</h2>"
            f"{f'<p><strong>When:</strong> {scheduled_label}</p>' if scheduled_label else ''}"
            f"{agenda_html}"
            f"<p><a href='{meeting_url}' style='display:inline-block;padding:10px 18px;"
            f"background:#4f46e5;color:#fff;border-radius:8px;text-decoration:none'>"
            f"Join in Donna</a></p>"
            f"<p style='color:#888;font-size:12px'>Donna prepares research before the "
            f"meeting and takes decisions &amp; action items during it.</p>"
            f"</body></html>"
        )
        return self._send(
            recipients,
            f"Invitation: {meeting_title}",
            html,
            ics_attachment=ics_attachment,
            ics_name="meeting.ics",
        )

    async def send_preread_email(
        self,
        recipients: List[str],
        meeting_title: str,
        meeting_goal: Optional[str],
        agenda_titles: List[str],
        findings: List[Dict[str, Any]],
    ) -> Optional[str]:
        """The PDF's pre-read: goal + agenda + tiered research findings."""
        agenda_html = "".join(f"<li>{t}</li>" for t in agenda_titles[:8])
        finding_rows = []
        for f in findings[:6]:
            link = (
                f" <a href='{f.get('source_url')}'>source</a>"
                if f.get("source_url")
                else ""
            )
            summary_text = str(f.get("summary", ""))[:300]
            finding_rows.append(
                f"<li><strong>{f.get('topic', '')}</strong>: {summary_text}{link}</li>"
            )
        findings_html = "".join(finding_rows)
        html = (
            f"<html><body style='font-family:sans-serif'>"
            f"<h2>Pre-read: {meeting_title}</h2>"
            f"{f'<p><strong>Goal:</strong> {meeting_goal}</p>' if meeting_goal else ''}"
            f"{f'<h3>Agenda</h3><ul>{agenda_html}</ul>' if agenda_html else ''}"
            f"{f'<h3>Key research</h3><ul>{findings_html}</ul>' if findings_html else ''}"
            f"<p style='color:#888;font-size:12px'>Prepared by Donna — 2 minutes now "
            f"saves 20 in the room.</p>"
            f"</body></html>"
        )
        return self._send(recipients, f"Pre-read: {meeting_title}", html)

    async def send_assignee_followups(
        self,
        assignments: Dict[str, List[Dict[str, Any]]],
        meeting_title: str,
    ) -> int:
        """Per-assignee task-list emails. Keys must be email addresses.

        Returns the number of emails sent (or mock-sent).
        """
        sent = 0
        for email, items in assignments.items():
            if not items:
                continue
            row_parts = []
            for i in items:
                due = (
                    f" — due {str(i.get('deadline'))[:10]}" if i.get("deadline") else ""
                )
                row_parts.append(
                    f"<li>{i.get('description', '')}{due}"
                    f" <em>({i.get('priority', 'medium')})</em></li>"
                )
            rows = "".join(row_parts)
            html = (
                f"<html><body style='font-family:sans-serif'>"
                f"<h2>Your action items from “{meeting_title}”</h2>"
                f"<ul>{rows}</ul>"
                f"<p style='color:#888;font-size:12px'>Tracked by Donna.</p>"
                f"</body></html>"
            )
            if self._send(
                [email],
                f"You own {len(items)} action item{'s' if len(items) != 1 else ''} "
                f"from {meeting_title}",
                html,
            ):
                sent += 1
        return sent

    def _render_html(self, title: str, summary: Dict[str, Any]) -> str:
        """Render the responsive HTML email from the Jinja2 template.

        Falls back to a minimal inline body if the template can't be
        loaded for any reason (so email delivery never hard-fails on a
        templating issue).
        """
        context = {
            "title": title,
            "exec_summary": summary.get("executive_summary", "No summary available."),
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
