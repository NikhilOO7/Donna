# apps/api/services/agents/__init__.py
"""
Document Intelligence Agents Module
Provides intelligent agents for document processing, voice interaction, and analytics
"""

from apps.api.services.agents.agent_coordinator import DocumentIntelligenceCoordinator
from apps.api.services.agents.analytics_agent import AnalyticsAgent
from apps.api.services.agents.base_agent import (
    AgentContext,
    AgentMetrics,
    AgentOrchestrator,
    BaseAgent,
)
from apps.api.services.agents.context_agent import ContextAgent
from apps.api.services.agents.document_agent import DocumentAgent
from apps.api.services.agents.query_agent import QueryAgent
from apps.api.services.agents.voice_agent import VoiceAgent

__all__ = [
    # Base classes
    "BaseAgent",
    "AgentContext",
    "AgentMetrics",
    "AgentOrchestrator",
    # Individual agents
    "DocumentAgent",
    "VoiceAgent",
    "QueryAgent",
    "ContextAgent",
    "AnalyticsAgent",
    # Coordinator
    "DocumentIntelligenceCoordinator",
]

# Version information
__version__ = "1.0.0"
__author__ = "Document Intelligence Team"
