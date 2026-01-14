# apps/api/services/agents/agent_coordinator.py
"""
Agent Coordinator - Orchestrates all agents for the Document Intelligence System
Manages agent interactions and complex workflows
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from crewai import Crew, Task, Process

from apps.api.services.agents.base_agent import AgentOrchestrator, AgentContext
from apps.api.services.agents.document_agent import DocumentAgent
from apps.api.services.agents.voice_agent import VoiceAgent
from apps.api.services.agents.query_agent import QueryAgent
from apps.api.services.agents.context_agent import ContextAgent
from apps.api.services.agents.analytics_agent import AnalyticsAgent
from apps.api.core.config import settings

logger = logging.getLogger(__name__)

class DocumentIntelligenceCoordinator:
    """
    Coordinates all agents to provide complete document intelligence functionality
    """
    
    def __init__(self):
        self.orchestrator = AgentOrchestrator()
        self.agents = {}
        self.crews = {}
        
        # Initialize all agents
        self._initialize_agents()
        
        # Define workflows
        self._define_workflows()
        
        # Create CrewAI crews for complex tasks
        self._create_crews()
    
    def _initialize_agents(self):
        """Initialize all document intelligence agents"""
        
        # Create agent instances
        self.document_agent = DocumentAgent()
        self.voice_agent = VoiceAgent()
        self.query_agent = QueryAgent()
        self.context_agent = ContextAgent()
        self.analytics_agent = AnalyticsAgent()
        
        # Register with orchestrator
        self.orchestrator.register_agent(self.document_agent)
        self.orchestrator.register_agent(self.voice_agent)
        self.orchestrator.register_agent(self.query_agent)
        self.orchestrator.register_agent(self.context_agent)
        self.orchestrator.register_agent(self.analytics_agent)
        
        # Store in dictionary for easy access
        self.agents = {
            "document": self.document_agent,
            "voice": self.voice_agent,
            "query": self.query_agent,
            "context": self.context_agent,
            "analytics": self.analytics_agent
        }
        
        logger.info("All agents initialized and registered")
    
    def _define_workflows(self):
        """Define standard workflows for common operations"""
        
        # Voice query workflow
        self.orchestrator.define_workflow(
            "voice_query",
            ["voice_agent", "query_agent", "context_agent", "voice_agent"]
        )
        
        # Document processing workflow
        self.orchestrator.define_workflow(
            "document_processing",
            ["document_agent", "analytics_agent"]
        )
        
        # Comprehensive search workflow
        self.orchestrator.define_workflow(
            "comprehensive_search",
            ["query_agent", "context_agent", "analytics_agent"]
        )
        
        # Insight generation workflow
        self.orchestrator.define_workflow(
            "insight_generation",
            ["analytics_agent", "context_agent"]
        )
    
    def _create_crews(self):
        """Create CrewAI crews for complex multi-agent tasks"""
        
        # Document Analysis Crew
        doc_analysis_crew = Crew(
            agents=[
                self.document_agent.get_crew_agent(),
                self.context_agent.get_crew_agent(),
                self.analytics_agent.get_crew_agent()
            ],
            tasks=[],  # Tasks will be added dynamically
            process=Process.sequential,
            verbose=True
        )
        self.crews["document_analysis"] = doc_analysis_crew
        
        # Voice Interaction Crew
        voice_crew = Crew(
            agents=[
                self.voice_agent.get_crew_agent(),
                self.query_agent.get_crew_agent(),
                self.context_agent.get_crew_agent()
            ],
            tasks=[],
            process=Process.sequential,
            verbose=True
        )
        self.crews["voice_interaction"] = voice_crew
        
        # Insight Generation Crew
        insight_crew = Crew(
            agents=[
                self.analytics_agent.get_crew_agent(),
                self.query_agent.get_crew_agent(),
                self.context_agent.get_crew_agent()
            ],
            tasks=[],
            process=Process.hierarchical,
            manager_llm=settings.openai_api_key,
            verbose=True
        )
        self.crews["insight_generation"] = insight_crew
    
    async def process_voice_query(
        self, 
        audio_data: bytes,
        session_id: str,
        room: Any = None
    ) -> Dict[str, Any]:
        """
        Process a voice query through the complete pipeline
        """
        context = AgentContext(
            conversation_id=session_id,
            session_id=session_id
        )
        
        try:
            # Step 1: Convert speech to text
            voice_result = await self.voice_agent.process({
                "action": "listen",
                "audio_data": audio_data
            }, context)
            
            if not voice_result.get("has_speech"):
                return {"status": "no_speech_detected"}
            
            transcript = voice_result["transcript"]
            
            # Track the query
            await self.analytics_agent.process({
                "action": "track",
                "event_data": {
                    "type": "query",
                    "query": transcript,
                    "source": "voice"
                }
            }, context)
            
            # Step 2: Process query for intent and enhancement
            query_result = await self.query_agent.process({
                "query": transcript,
                "conversation_history": context.metadata.get("history", [])
            }, context)
            
            # Step 3: Search for relevant content
            search_result = await self.context_agent.process({
                "query": query_result["enhanced_query"],
                "context_levels": query_result["context_requirements"]["levels"],
                "filters": {},
                "search_parameters": query_result["search_parameters"]
            }, context)
            
            # Step 4: Generate response
            response = self._generate_voice_response(
                search_result["results"],
                query_result["intent"]
            )
            
            # Step 5: Convert response to speech
            tts_result = await self.voice_agent.process({
                "action": "speak",
                "text": response,
                "emotion": "friendly"
            }, context)
            
            # Update conversation history
            context.metadata.setdefault("history", []).append({
                "timestamp": datetime.now().isoformat(),
                "user": transcript,
                "assistant": response
            })
            
            return {
                "transcript": transcript,
                "response": response,
                "audio_stream": tts_result["audio_stream"],
                "search_results": search_result["results"][:3],  # Top 3
                "intent": query_result["intent"],
                "metrics": {
                    "total_results": len(search_result["results"]),
                    "processing_time": sum([
                        voice_result["metrics"].get("stt_latency_ms", 0),
                        query_result["processing_metrics"].get("processing_time_ms", 0),
                        search_result["search_metrics"].get("processing_time_ms", 0),
                        tts_result["metrics"].get("tts_latency_ms", 0)
                    ])
                }
            }
            
        except Exception as e:
            logger.error(f"Voice query processing failed: {e}")
            
            # Generate error response
            error_response = "I'm sorry, I encountered an error processing your request. Please try again."
            
            tts_result = await self.voice_agent.process({
                "action": "speak",
                "text": error_response,
                "emotion": "apologetic"
            }, context)
            
            return {
                "error": str(e),
                "response": error_response,
                "audio_stream": tts_result.get("audio_stream")
            }
    
    async def process_document(
        self,
        document_path: str,
        document_type: str,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a document through the complete pipeline
        """
        context = AgentContext(
            conversation_id=f"doc_process_{datetime.now().timestamp()}",
            user_id=user_id
        )
        
        try:
            # Step 1: Process document with Document Agent
            doc_result = await self.document_agent.process({
                "document_path": document_path,
                "document_type": document_type,
                "processing_options": {
                    "extract_metadata": True,
                    "generate_embeddings": True,
                    "map_relationships": True
                }
            }, context)
            
            # Step 2: Store in vector store via Context Agent
            # (Context Agent has access to vector store)
            
            # Step 3: Track document processing
            await self.analytics_agent.process({
                "action": "track",
                "event_data": {
                    "type": "document_processed",
                    "document_id": doc_result["document_id"],
                    "chunk_count": doc_result["processing_metrics"]["chunk_count"],
                    "processing_time": doc_result["processing_metrics"]["processing_time_ms"]
                }
            }, context)
            
            # Step 4: Generate initial insights about the document
            insights = await self._generate_document_insights(doc_result)
            
            return {
                "document_id": doc_result["document_id"],
                "metadata": doc_result["metadata"],
                "structure": doc_result["structure"],
                "chunks_created": doc_result["processing_metrics"]["chunk_count"],
                "relationships": doc_result["relationships"],
                "insights": insights,
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            
            # Track error
            await self.analytics_agent.process({
                "action": "track",
                "event_data": {
                    "type": "error",
                    "error_type": "document_processing",
                    "error_message": str(e)
                }
            }, context)
            
            return {
                "error": str(e),
                "status": "failed"
            }
    
    async def generate_insights(
        self,
        time_range: str = "24h",
        focus_areas: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive insights about system usage
        """
        context = AgentContext(
            conversation_id=f"insights_{datetime.now().timestamp()}"
        )
        
        try:
            # Run comprehensive analytics
            analytics_result = await self.analytics_agent.process({
                "action": "analyze",
                "time_range": time_range
            }, context)
            
            # Get additional context about top queries
            if analytics_result["patterns"].get("query_patterns"):
                top_queries = [p["pattern"] for p in analytics_result["patterns"]["query_patterns"][:5]]
                
                # Search for content related to top queries
                search_tasks = []
                for query in top_queries:
                    task = self.context_agent.process({
                        "query": query,
                        "context_levels": ["local"],
                        "filters": {},
                        "search_parameters": {"max_results": 3}
                    }, context)
                    search_tasks.append(task)
                
                search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
                
                # Analyze search coverage
                coverage_analysis = self._analyze_search_coverage(
                    top_queries,
                    search_results,
                    analytics_result["knowledge_gaps"]
                )
                
                analytics_result["coverage_analysis"] = coverage_analysis
            
            # Create executive summary
            executive_summary = self._create_executive_summary(analytics_result)
            
            return {
                "executive_summary": executive_summary,
                "insights": analytics_result["insights"],
                "patterns": analytics_result["patterns"],
                "knowledge_gaps": analytics_result["knowledge_gaps"],
                "recommendations": analytics_result["recommendations"],
                "coverage_analysis": analytics_result.get("coverage_analysis", {}),
                "time_range": time_range,
                "generated_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Insight generation failed: {e}")
            return {
                "error": str(e),
                "status": "failed"
            }
    
    async def run_crew_task(
        self,
        crew_name: str,
        task_description: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Run a complex task using a CrewAI crew
        """
        if crew_name not in self.crews:
            raise ValueError(f"Unknown crew: {crew_name}")
        
        crew = self.crews[crew_name]
        
        # Create tasks based on description
        if crew_name == "document_analysis":
            tasks = self._create_document_analysis_tasks(task_description, context)
        elif crew_name == "voice_interaction":
            tasks = self._create_voice_interaction_tasks(task_description, context)
        elif crew_name == "insight_generation":
            tasks = self._create_insight_generation_tasks(task_description, context)
        else:
            tasks = []
        
        # Assign tasks to crew
        crew.tasks = tasks
        
        # Run crew
        try:
            result = crew.kickoff()
            return {
                "status": "success",
                "crew": crew_name,
                "result": result,
                "tasks_completed": len(tasks)
            }
        except Exception as e:
            logger.error(f"Crew task failed: {e}")
            return {
                "status": "failed",
                "crew": crew_name,
                "error": str(e)
            }
    
    def _generate_voice_response(
        self,
        search_results: List[Dict[str, Any]],
        intent: Dict[str, Any]
    ) -> str:
        """Generate natural voice response from search results"""
        
        if not search_results:
            return "I couldn't find any information about that in the documents. Could you please rephrase your question or ask about something else?"
        
        # Get intent type
        intent_type = intent.get("pattern_intent", "general")
        
        # Format response based on intent
        if intent_type == "definition":
            # Provide clear definition
            top_result = search_results[0]
            response = f"Based on the documents, {top_result['content'][:200]}..."
            
        elif intent_type == "listing":
            # Provide list format
            items = []
            for i, result in enumerate(search_results[:3]):
                items.append(f"{i+1}. {result['content'][:100]}")
            response = "Here's what I found:\n" + "\n".join(items)
            
        elif intent_type == "comparison":
            # Provide comparison
            if len(search_results) >= 2:
                response = f"Comparing the information, {search_results[0]['content'][:150]}... while {search_results[1]['content'][:150]}..."
            else:
                response = f"I found information about {search_results[0]['content'][:200]}..."
                
        else:
            # General response
            top_result = search_results[0]
            response = f"According to the documents, {top_result['content'][:250]}..."
        
        # Add confidence indicator if low relevance
        if search_results[0].get("final_score", 1.0) < 0.5:
            response += " However, this might not fully answer your question. Would you like me to search for something more specific?"
        
        return response
    
    async def _generate_document_insights(
        self,
        doc_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate insights about a processed document"""
        
        insights = []
        
        # Document complexity insight
        metadata = doc_result.get("metadata", {})
        token_count = doc_result.get("structure", {}).get("token_count", 0)
        
        if token_count > 10000:
            insights.append({
                "type": "complexity",
                "title": "Large Document",
                "description": f"This document contains {token_count:,} tokens and may benefit from summary generation",
                "recommendation": "Consider creating an executive summary"
            })
        
        # Topic coverage insight
        topics = metadata.get("topics", [])
        if topics:
            insights.append({
                "type": "content",
                "title": "Main Topics",
                "description": f"Document covers: {', '.join(topics[:5])}",
                "recommendation": "Ensure related documents are also uploaded for comprehensive coverage"
            })
        
        # Relationship insight
        relationships = doc_result.get("relationships", {})
        if relationships.get("references"):
            insights.append({
                "type": "relationships",
                "title": "Document References",
                "description": "This document references other materials",
                "recommendation": "Upload referenced documents for better context"
            })
        
        return insights
    
    def _analyze_search_coverage(
        self,
        queries: List[str],
        search_results: List[Any],
        knowledge_gaps: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze how well the system covers top queries"""
        
        coverage_stats = {
            "well_covered": 0,
            "partially_covered": 0,
            "not_covered": 0,
            "details": []
        }
        
        for i, (query, results) in enumerate(zip(queries, search_results)):
            if isinstance(results, Exception):
                coverage_stats["not_covered"] += 1
                coverage_stats["details"].append({
                    "query": query,
                    "coverage": "error",
                    "issue": str(results)
                })
            elif not results or not results.get("results"):
                coverage_stats["not_covered"] += 1
                coverage_stats["details"].append({
                    "query": query,
                    "coverage": "none",
                    "issue": "No results found"
                })
            else:
                top_score = results["results"][0].get("final_score", 0)
                if top_score > 0.7:
                    coverage_stats["well_covered"] += 1
                    coverage = "good"
                elif top_score > 0.4:
                    coverage_stats["partially_covered"] += 1
                    coverage = "partial"
                else:
                    coverage_stats["not_covered"] += 1
                    coverage = "poor"
                
                coverage_stats["details"].append({
                    "query": query,
                    "coverage": coverage,
                    "top_score": top_score
                })
        
        return coverage_stats
    
    def _create_executive_summary(
        self,
        analytics_result: Dict[str, Any]
    ) -> str:
        """Create executive summary from analytics results"""
        
        summary_parts = []
        
        # Usage summary
        patterns = analytics_result.get("patterns", {})
        if patterns.get("total_events"):
            summary_parts.append(
                f"System processed {patterns['total_events']} queries in the analyzed period."
            )
        
        # Top insights
        insights = analytics_result.get("insights", [])
        if insights:
            top_insight = insights[0]
            summary_parts.append(
                f"Key finding: {top_insight.get('description', 'No description')}"
            )
        
        # Critical gaps
        gaps = analytics_result.get("knowledge_gaps", {}).get("gaps", [])
        if gaps:
            summary_parts.append(
                f"Identified {len(gaps)} knowledge gaps requiring attention."
            )
        
        # Performance
        performance = analytics_result.get("performance", {})
        if performance.get("statistics"):
            avg_latency = performance["statistics"].get("average_latency_ms", 0)
            summary_parts.append(
                f"Average response time: {avg_latency:.0f}ms"
            )
        
        return " ".join(summary_parts)
    
    def _create_document_analysis_tasks(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> List[Task]:
        """Create tasks for document analysis crew"""
        
        tasks = []
        
        # Task 1: Deep document analysis
        tasks.append(Task(
            description=f"Perform deep analysis of document: {description}",
            agent=self.document_agent.get_crew_agent(),
            expected_output="Comprehensive document analysis with structure, themes, and insights"
        ))
        
        # Task 2: Context mapping
        tasks.append(Task(
            description="Map document relationships and context connections",
            agent=self.context_agent.get_crew_agent(),
            expected_output="Document relationship map and context analysis"
        ))
        
        # Task 3: Usage prediction
        tasks.append(Task(
            description="Predict how this document will be used based on content",
            agent=self.analytics_agent.get_crew_agent(),
            expected_output="Usage predictions and recommendations"
        ))
        
        return tasks
    
    def _create_voice_interaction_tasks(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> List[Task]:
        """Create tasks for voice interaction crew"""
        
        tasks = []
        
        # Task 1: Optimize voice recognition
        tasks.append(Task(
            description=f"Optimize voice recognition for: {description}",
            agent=self.voice_agent.get_crew_agent(),
            expected_output="Voice recognition optimization recommendations"
        ))
        
        # Task 2: Query understanding
        tasks.append(Task(
            description="Enhance query understanding for voice inputs",
            agent=self.query_agent.get_crew_agent(),
            expected_output="Query patterns and enhancement strategies"
        ))
        
        # Task 3: Response optimization
        tasks.append(Task(
            description="Optimize response generation for voice output",
            agent=self.context_agent.get_crew_agent(),
            expected_output="Response generation strategies"
        ))
        
        return tasks
    
    def _create_insight_generation_tasks(
        self,
        description: str,
        context: Dict[str, Any]
    ) -> List[Task]:
        """Create tasks for insight generation crew"""
        
        tasks = []
        
        # Task 1: Comprehensive analysis
        tasks.append(Task(
            description=f"Perform comprehensive system analysis: {description}",
            agent=self.analytics_agent.get_crew_agent(),
            expected_output="Detailed analytics report with patterns and trends"
        ))
        
        # Task 2: Gap identification
        tasks.append(Task(
            description="Identify knowledge and coverage gaps",
            agent=self.query_agent.get_crew_agent(),
            expected_output="Gap analysis with severity ratings"
        ))
        
        # Task 3: Recommendation generation
        tasks.append(Task(
            description="Generate actionable recommendations",
            agent=self.context_agent.get_crew_agent(),
            expected_output="Prioritized recommendations with implementation steps"
        ))
        
        return tasks
    
    def get_agent_metrics(self) -> Dict[str, Any]:
        """Get metrics from all agents"""
        return self.orchestrator.get_metrics_summary()
    
    def get_agent_status(self) -> Dict[str, Any]:
        """Get status of all agents"""
        status = {}
        
        for name, agent in self.agents.items():
            status[name] = {
                "operational": True,
                "operations_count": agent.metrics.operations_count,
                "average_latency_ms": agent.metrics.average_latency,
                "error_rate": agent.metrics.errors_count / max(agent.metrics.operations_count, 1)
            }
        
        return status