"""
SQLAlchemy model registry.

Importing ANY model must register ALL of them, because SQLAlchemy resolves
foreign keys against ``Base.metadata`` at statement-compile time — not at
class-definition time. A model whose FK target has not been imported yet
cannot be inserted.

This is not theoretical. ``AnalyticsEvent.document_id`` declares
``ForeignKey("doc_intel.documents.id")``, but ``main.py`` imported the
``Document`` model only *inside function bodies*. So at startup
``doc_intel.analytics_events`` was registered while ``doc_intel.documents``
was not, and every analytics write failed with:

    Foreign key associated with column 'analytics_events.document_id'
    could not find table 'doc_intel.documents'

...caught by ``track_event``'s except-and-log, so the product looked healthy
while its telemetry silently wrote nothing. It would then start working after
any request that happened to import ``Document``, which is the worst kind of
bug: intermittent, invisible, and order-dependent.

Because this module is the package ``__init__``, ``from apps.api.models.x
import Y`` executes it first — so every entry point gets a complete metadata
registry with no discipline required at the call site.

Keep this list exhaustive. A new model that is not listed here reintroduces
exactly the failure above.
"""

from apps.api.models.analytics import AnalyticsEvent, ConversationSession
from apps.api.models.data_connection import DataConnection, DataQueryLog
from apps.api.models.document import (
    ContextualEmbedding,
    Document,
    DocumentChunk,
    Entity,
)
from apps.api.models.meeting import (
    ActionItem,
    Decision,
    DocumentElement,
    EntityRelationship,
    Meeting,
    MeetingDocument,
    MeetingSummary,
    MeetingTranscript,
    Nudge,
    ResearchBrief,
)
from apps.api.models.outbox import KGOutbox
from apps.api.models.user import User

__all__ = [
    "ActionItem",
    "AnalyticsEvent",
    "ContextualEmbedding",
    "ConversationSession",
    "DataConnection",
    "DataQueryLog",
    "Decision",
    "Document",
    "DocumentChunk",
    "DocumentElement",
    "Entity",
    "EntityRelationship",
    "KGOutbox",
    "Meeting",
    "MeetingDocument",
    "MeetingSummary",
    "MeetingTranscript",
    "Nudge",
    "ResearchBrief",
    "User",
]
