"""
Email Service.

Sends meeting summaries via Postmark. Gracefully degrades if
Postmark API key is not configured.
"""

import logging
from typing import Any, Dict, List, Optional

from apps.api.core.config import settings

logger = logging.getLogger(__name__)


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
        """Render a clean, responsive HTML email."""
        exec_summary = summary.get("executive_summary", "No summary available.")
        decisions = summary.get("decisions_summary", [])
        actions = summary.get("action_items", [])
        insights = summary.get("ai_insights_used", [])
        follow_ups = summary.get("follow_up_recommendations", [])

        decisions_html = ""
        if decisions:
            rows = "".join(
                f'<tr><td style="padding:8px 12px;border-bottom:1px solid #f0f0f0">{d.get("decision", "")}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #f0f0f0">{d.get("owner", "TBD")}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #f0f0f0">{d.get("deadline", "TBD")}</td></tr>'
                for d in decisions
            )
            decisions_html = f"""
            <h2 style="color:#312e81;font-size:18px;margin:24px 0 12px">Decisions</h2>
            <table style="width:100%;border-collapse:collapse;font-size:14px">
                <thead><tr style="background:#eef2ff">
                    <th style="padding:8px 12px;text-align:left">Decision</th>
                    <th style="padding:8px 12px;text-align:left">Owner</th>
                    <th style="padding:8px 12px;text-align:left">Deadline</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>"""

        actions_html = ""
        if actions:
            items = "".join(
                f'<li style="margin-bottom:6px"><strong>{a.get("item", "")}</strong>'
                f" — {a.get('assignee', 'Unassigned')} "
                f'<span style="color:#6366f1">({a.get("priority", "medium")})</span></li>'
                for a in actions
            )
            actions_html = f"""
            <h2 style="color:#312e81;font-size:18px;margin:24px 0 12px">Action Items</h2>
            <ul style="padding-left:20px;font-size:14px">{items}</ul>"""

        insights_html = ""
        if insights:
            items = "".join(
                f'<li style="margin-bottom:6px">{i.get("insight", "")}'
                f' <em style="color:#888">— {i.get("impact", "")}</em></li>'
                for i in insights
            )
            insights_html = f"""
            <h2 style="color:#312e81;font-size:18px;margin:24px 0 12px">AI Insights Used</h2>
            <ul style="padding-left:20px;font-size:14px">{items}</ul>"""

        follow_html = ""
        if follow_ups:
            items = "".join(
                f'<li style="margin-bottom:4px">{f}</li>' for f in follow_ups
            )
            follow_html = f"""
            <h2 style="color:#312e81;font-size:18px;margin:24px 0 12px">Follow-Up Recommendations</h2>
            <ul style="padding-left:20px;font-size:14px">{items}</ul>"""

        return f"""
        <!DOCTYPE html>
        <html>
        <body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f9fafb">
            <div style="max-width:640px;margin:0 auto;padding:32px 24px">
                <div style="background:linear-gradient(135deg,#4f46e5,#6366f1);border-radius:12px;padding:24px 28px;color:white;margin-bottom:24px">
                    <h1 style="margin:0;font-size:22px;font-weight:700">{title}</h1>
                    <p style="margin:6px 0 0;opacity:0.85;font-size:14px">Meeting Summary — AI Generated</p>
                </div>
                <div style="background:white;border-radius:12px;padding:28px;border:1px solid #e5e7eb">
                    <h2 style="color:#312e81;font-size:18px;margin:0 0 12px">Executive Summary</h2>
                    <p style="color:#374151;line-height:1.7;font-size:14px;white-space:pre-wrap">{exec_summary}</p>
                    {decisions_html}
                    {actions_html}
                    {insights_html}
                    {follow_html}
                </div>
                <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:24px">
                    Generated by Meeting Assistant &middot; AI-Powered Meeting Intelligence
                </p>
            </div>
        </body>
        </html>"""


email_service = EmailService()
