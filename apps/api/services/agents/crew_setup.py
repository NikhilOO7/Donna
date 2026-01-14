"""
Enhanced CrewAI agents setup preserving all original functionality while adding new capabilities
"""

# Original imports preserved
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from typing import List, Dict, Any, Optional

# Enhanced imports
from openai import OpenAI
import asyncio
import json

from apps.api.core.config import settings
from apps.api.services.rag.llamaindex_service import ModernRAGService
from apps.api.services.document.vector_store import ModernVectorStore

class DocumentIntelligenceAgents:
    """Enhanced DocumentIntelligenceAgents preserving all original functionality"""
    
    def __init__(self):
        self.llm = OpenAI(api_key=settings.openai_api_key)
        
        # Enhanced services
        self.modern_rag = ModernRAGService()
        self.modern_vector_store = ModernVectorStore()
        
    def create_agents(self) -> List[Agent]:
        """Create agents - preserving original structure with enhancements"""
        
        # Original Document Analyst Agent (preserved + enhanced)
        analyst = Agent(
            role="Enhanced Document Analyst",
            goal="Extract key insights and structure from documents using advanced AI techniques",
            backstory="Expert in document analysis and information extraction with contextual understanding capabilities",
            tools=[
                self.document_analysis_tool,
                self.enhanced_document_analysis_tool,  # New enhanced tool
                self.contextual_extraction_tool  # New tool
            ],
            llm=self.llm,
            verbose=True
        )
        
        # Original Decision Extractor Agent (preserved + enhanced)
        decision_extractor = Agent(
            role="Enhanced Decision Extractor", 
            goal="Identify decisions and action items from conversations with contextual awareness",
            backstory="Specialist in meeting analysis and decision tracking with multi-document context understanding",
            tools=[
                self.decision_extraction_tool,
                self.enhanced_decision_extraction_tool,  # New enhanced tool
                self.cross_document_analysis_tool  # New tool
            ],
            llm=self.llm
        )
        
        # Original Knowledge Graph Builder (preserved + enhanced)
        graph_builder = Agent(
            role="Enhanced Knowledge Graph Builder",
            goal="Build relationships between entities and concepts across multiple contexts",
            backstory="Expert in knowledge representation and graph construction with multi-level context integration",
            tools=[
                self.graph_building_tool,
                self.enhanced_graph_building_tool,  # New enhanced tool
                self.semantic_relationship_tool  # New tool
            ],
            llm=self.llm
        )
        
        # New Enhanced Agent - Multi-Context Synthesizer
        context_synthesizer = Agent(
            role="Multi-Context Synthesizer",
            goal="Synthesize information across local, document, and global contexts",
            backstory="Specialist in contextual information synthesis and cross-document intelligence",
            tools=[
                self.context_synthesis_tool,
                self.cross_context_analysis_tool,
                self.semantic_integration_tool
            ],
            llm=self.llm
        )
        
        return [analyst, decision_extractor, graph_builder, context_synthesizer]
    
    # Original tools preserved exactly
    @tool("Document Analysis")
    def document_analysis_tool(self, document_text: str) -> str:
        """Analyze document structure and extract key information - original functionality preserved"""
        try:
            # Original implementation preserved
            analysis_prompt = f"""
            Analyze this document and extract:
            1. Main topics and themes
            2. Document structure
            3. Key entities mentioned
            4. Important relationships
            
            Document: {document_text[:1000]}...
            
            Provide structured analysis.
            """
            
            # Use original approach
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": analysis_prompt}],
                max_tokens=500
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Document analysis failed: {str(e)}"
    
    @tool("Decision Extraction")
    def decision_extraction_tool(self, conversation_text: str) -> str:
        """Extract decisions and action items - original functionality preserved"""
        try:
            # Original implementation preserved
            extraction_prompt = f"""
            Extract decisions and action items from this conversation:
            
            {conversation_text[:1000]}...
            
            Format:
            DECISIONS:
            - [Decision 1]
            - [Decision 2]
            
            ACTION ITEMS:
            - [Action 1] (Owner: [Name], Due: [Date])
            - [Action 2] (Owner: [Name], Due: [Date])
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": extraction_prompt}],
                max_tokens=400
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Decision extraction failed: {str(e)}"
    
    @tool("Graph Building")
    def graph_building_tool(self, entities_text: str) -> str:
        """Build knowledge graph relationships - original functionality preserved"""
        try:
            # Original implementation preserved
            graph_prompt = f"""
            Create knowledge graph relationships from these entities:
            
            {entities_text[:800]}...
            
            Format as:
            ENTITIES: [entity1, entity2, entity3]
            RELATIONSHIPS: 
            - entity1 -> RELATES_TO -> entity2
            - entity2 -> CONTAINS -> entity3
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo", 
                messages=[{"role": "user", "content": graph_prompt}],
                max_tokens=400
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Graph building failed: {str(e)}"
    
    # Enhanced tools (new functionality)
    @tool("Enhanced Document Analysis")
    def enhanced_document_analysis_tool(self, document_text: str, context_type: str = "document") -> str:
        """Enhanced document analysis with contextual understanding"""
        try:
            analysis_prompt = f"""
            Perform enhanced document analysis with {context_type} context:
            
            Document: {document_text[:1200]}...
            
            Provide enhanced analysis including:
            1. Semantic themes and concepts
            2. Contextual relationships
            3. Cross-reference potential
            4. Information density assessment
            5. Key insights for RAG optimization
            
            Format as structured JSON.
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": analysis_prompt}],
                max_tokens=600,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Enhanced document analysis failed: {str(e)}"
    
    @tool("Contextual Extraction")
    def contextual_extraction_tool(self, text: str, extraction_type: str = "concepts") -> str:
        """Extract contextual information with multi-level understanding"""
        try:
            extraction_prompt = f"""
            Extract {extraction_type} with contextual awareness:
            
            Text: {text[:1000]}...
            
            Provide:
            1. Primary {extraction_type}
            2. Secondary {extraction_type}  
            3. Contextual relationships
            4. Semantic connections
            5. Cross-document potential
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": extraction_prompt}],
                max_tokens=500,
                temperature=0.2
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Contextual extraction failed: {str(e)}"
    
    @tool("Enhanced Decision Extraction")
    def enhanced_decision_extraction_tool(self, conversation_text: str, context_history: str = "") -> str:
        """Enhanced decision extraction with conversation context"""
        try:
            extraction_prompt = f"""
            Enhanced decision extraction with context awareness:
            
            Current Conversation: {conversation_text[:800]}...
            
            Context History: {context_history[:400]}...
            
            Extract with enhanced understanding:
            1. Explicit decisions made
            2. Implicit decisions inferred
            3. Action items with context
            4. Dependencies identified
            5. Follow-up requirements
            6. Stakeholder implications
            
            Provide structured output with confidence levels.
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": extraction_prompt}],
                max_tokens=600,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Enhanced decision extraction failed: {str(e)}"
    
    @tool("Cross Document Analysis") 
    def cross_document_analysis_tool(self, query: str, document_context: str = "") -> str:
        """Analyze information across multiple documents"""
        try:
            # Use enhanced RAG for cross-document analysis
            analysis_result = asyncio.run(
                self.modern_rag.process_query(
                    query=f"Cross-document analysis: {query}",
                    context_types=["document", "global", "semantic"]
                )
            )
            
            synthesis_prompt = f"""
            Synthesize cross-document analysis:
            
            Query: {query}
            
            Retrieved Information: {json.dumps(analysis_result.get('sources', [])[:3])}
            
            Context: {document_context[:400]}...
            
            Provide comprehensive cross-document insights including:
            1. Common themes across documents
            2. Contradictions or conflicts
            3. Complementary information
            4. Missing information gaps
            5. Synthesis recommendations
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": synthesis_prompt}],
                max_tokens=700,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Cross-document analysis failed: {str(e)}"
    
    @tool("Enhanced Graph Building")
    def enhanced_graph_building_tool(self, entities_text: str, context_level: str = "document") -> str:
        """Enhanced knowledge graph building with contextual relationships"""
        try:
            graph_prompt = f"""
            Build enhanced knowledge graph with {context_level} context:
            
            Entities: {entities_text[:1000]}...
            
            Create enhanced graph including:
            1. Primary entity relationships
            2. Contextual relationships
            3. Semantic relationships  
            4. Hierarchical relationships
            5. Temporal relationships
            6. Cross-document connections
            
            Format as structured graph notation with relationship strengths.
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": graph_prompt}],
                max_tokens=600,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Enhanced graph building failed: {str(e)}"
    
    @tool("Semantic Relationship Analysis")
    def semantic_relationship_tool(self, concept1: str, concept2: str, context: str = "") -> str:
        """Analyze semantic relationships between concepts"""
        try:
            relationship_prompt = f"""
            Analyze semantic relationship between concepts:
            
            Concept 1: {concept1}
            Concept 2: {concept2}
            Context: {context[:500]}...
            
            Provide analysis including:
            1. Direct relationship type
            2. Semantic similarity score
            3. Contextual relevance
            4. Conceptual hierarchy
            5. Usage patterns
            6. Cross-reference potential
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": relationship_prompt}],
                max_tokens=400,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Semantic relationship analysis failed: {str(e)}"
    
    # New enhanced tools for Multi-Context Synthesizer
    @tool("Context Synthesis")
    def context_synthesis_tool(self, local_context: str, document_context: str, global_context: str) -> str:
        """Synthesize information across multiple context levels"""
        try:
            synthesis_prompt = f"""
            Synthesize multi-level context information:
            
            Local Context: {local_context[:300]}...
            Document Context: {document_context[:300]}...
            Global Context: {global_context[:300]}...
            
            Provide synthesis including:
            1. Context alignment analysis
            2. Information consistency check
            3. Complementary insights
            4. Context-specific recommendations
            5. Integrated understanding
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": synthesis_prompt}],
                max_tokens=500,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Context synthesis failed: {str(e)}"
    
    @tool("Cross Context Analysis")
    def cross_context_analysis_tool(self, query: str, context_types: List[str] = None) -> str:
        """Analyze query across different context types"""
        if context_types is None:
            context_types = ["local", "document", "global", "semantic"]
        
        try:
            # Use enhanced vector store for multi-context search
            analysis_results = {}
            
            for context_type in context_types:
                try:
                    # This would integrate with the enhanced RAG system
                    result = asyncio.run(
                        self.modern_rag.process_query(
                            query=query,
                            context_types=[context_type]
                        )
                    )
                    analysis_results[context_type] = result.get('answer', 'No result')[:200]
                except:
                    analysis_results[context_type] = "Analysis unavailable"
            
            synthesis_prompt = f"""
            Cross-context analysis results for query: "{query}"
            
            Results by context type:
            {json.dumps(analysis_results, indent=2)}
            
            Provide comprehensive analysis including:
            1. Context-specific insights
            2. Cross-context patterns
            3. Information gaps
            4. Recommended context focus
            5. Synthesis recommendations
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": synthesis_prompt}],
                max_tokens=600,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Cross-context analysis failed: {str(e)}"
    
    @tool("Semantic Integration")
    def semantic_integration_tool(self, concepts: List[str], integration_type: str = "hierarchical") -> str:
        """Integrate semantic concepts using specified integration approach"""
        try:
            integration_prompt = f"""
            Perform {integration_type} semantic integration:
            
            Concepts: {', '.join(concepts[:10])}
            
            Integration approach: {integration_type}
            
            Provide integration including:
            1. Concept relationships
            2. Integration hierarchy
            3. Semantic clusters
            4. Integration confidence
            5. Usage recommendations
            """
            
            response = self.llm.chat.completions.create(
                model="gpt-4-turbo",
                messages=[{"role": "user", "content": integration_prompt}],
                max_tokens=500,
                temperature=0.1
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Semantic integration failed: {str(e)}"
    
    def create_enhanced_crew(self, task_type: str = "document_analysis") -> Crew:
        """Create an enhanced crew for specific tasks"""
        agents = self.create_agents()
        
        if task_type == "document_analysis":
            return Crew(
                agents=[agents[0], agents[3]],  # Analyst + Context Synthesizer
                tasks=[],  # Tasks would be defined based on specific needs
                process=Process.sequential,
                verbose=True
            )
        elif task_type == "cross_document_intelligence":
            return Crew(
                agents=agents,  # All agents
                tasks=[],
                process=Process.hierarchical,
                verbose=True
            )
        else:
            return Crew(
                agents=agents[:2],  # Default to first two agents
                tasks=[],
                process=Process.sequential,
                verbose=True
            )