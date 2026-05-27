# apps/api/services/agents/base_agent.py
"""
Base Agent class for all document intelligence agents
Provides common functionality and interfaces
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from crewai import Agent as CrewAgent
from openai import AsyncOpenAI

from apps.api.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AgentMetrics:
    """Track agent performance metrics"""

    operations_count: int = 0
    total_latency: float = 0
    errors_count: int = 0
    last_operation_time: Optional[datetime] = None

    def record_operation(self, latency: float):
        """Record successful operation metrics"""
        self.operations_count += 1
        self.total_latency += latency
        self.last_operation_time = datetime.now()

    def record_error(self):
        """Record operation error"""
        self.errors_count += 1

    @property
    def average_latency(self) -> float:
        """Calculate average operation latency"""
        if self.operations_count == 0:
            return 0
        return self.total_latency / self.operations_count


@dataclass
class AgentContext:
    """Shared context for agent operations"""

    conversation_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


class BaseAgent(ABC):
    """Abstract base class for all document intelligence agents"""

    def __init__(self, name: str, role: str, goal: str, backstory: str):
        self.name = name
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self.metrics = AgentMetrics()
        self.openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._tools: List[Any] = []  # CrewAI tools (decorated functions)
        self._crew_agent: Optional[CrewAgent] = None

        # Initialize agent-specific components
        self._initialize()

    @abstractmethod
    def _initialize(self):
        """Initialize agent-specific components"""
        pass

    @abstractmethod
    async def process(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Main processing method for the agent"""
        pass

    def register_tool(self, tool: Any):
        """Register a tool for the agent to use"""
        self._tools.append(tool)
        tool_name = getattr(tool, "name", getattr(tool, "__name__", "unknown"))
        logger.info(f"Tool '{tool_name}' registered for agent '{self.name}'")

    def get_crew_agent(self) -> CrewAgent:
        """Get or create CrewAI agent instance"""
        if not self._crew_agent:
            self._crew_agent = CrewAgent(
                role=self.role,
                goal=self.goal,
                backstory=self.backstory,
                tools=self._tools,
                llm=self.openai_client,
                verbose=True,
                allow_delegation=False,
            )
        return self._crew_agent

    async def measure_operation(self, operation: Callable) -> Any:
        """Measure operation latency and record metrics"""
        start_time = time.time()
        try:
            result = await operation()
            latency = (time.time() - start_time) * 1000  # Convert to ms
            self.metrics.record_operation(latency)
            return result
        except Exception as e:
            self.metrics.record_error()
            logger.error(f"Agent '{self.name}' operation failed: {e}")
            raise

    def log_metrics(self):
        """Log current agent metrics"""
        logger.info(
            f"Agent '{self.name}' Metrics - "
            f"Operations: {self.metrics.operations_count}, "
            f"Avg Latency: {self.metrics.average_latency:.2f}ms, "
            f"Errors: {self.metrics.errors_count}"
        )


class AgentOrchestrator:
    """Orchestrates multiple agents for complex workflows"""

    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {}
        self.workflows: Dict[str, List[str]] = {}

    def register_agent(self, agent: BaseAgent):
        """Register an agent with the orchestrator"""
        self.agents[agent.name] = agent
        logger.info(f"Agent '{agent.name}' registered with orchestrator")

    def define_workflow(self, name: str, agent_sequence: List[str]):
        """Define a workflow as a sequence of agents"""
        self.workflows[name] = agent_sequence
        logger.info(f"Workflow '{name}' defined with agents: {agent_sequence}")

    async def execute_workflow(
        self, workflow_name: str, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Execute a defined workflow"""
        if workflow_name not in self.workflows:
            raise ValueError(f"Unknown workflow: {workflow_name}")

        agent_sequence = self.workflows[workflow_name]
        result = input_data

        for agent_name in agent_sequence:
            if agent_name not in self.agents:
                raise ValueError(f"Unknown agent in workflow: {agent_name}")

            agent = self.agents[agent_name]
            logger.info(f"Executing agent '{agent_name}' in workflow '{workflow_name}'")

            result = await agent.process(result, context)

        return result

    def get_metrics_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics summary for all agents"""
        summary = {}
        for name, agent in self.agents.items():
            summary[name] = {
                "operations": agent.metrics.operations_count,
                "average_latency_ms": agent.metrics.average_latency,
                "errors": agent.metrics.errors_count,
                "last_operation": agent.metrics.last_operation_time.isoformat()
                if agent.metrics.last_operation_time
                else None,
            }
        return summary
