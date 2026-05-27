# apps/api/services/agents/query_agent.py
"""
Query Agent - Handles intent recognition and query enhancement
Understands what users really mean and optimizes queries for better results
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import spacy
from crewai.tools import tool

from apps.api.services.agents.base_agent import AgentContext, BaseAgent

logger = logging.getLogger(__name__)


class QueryAgent(BaseAgent):
    """
    Query Agent - Translator that understands user intent

    Responsibilities:
    - Intent recognition and classification
    - Query enhancement and expansion
    - Contextual memory management
    - Query reformulation for better search
    - Conversation state tracking
    """

    def __init__(self):
        super().__init__(
            name="query_agent",
            role="Query Understanding Specialist",
            goal="Transform user queries into optimized search requests by understanding true intent",
            backstory="""I am an expert in natural language understanding, specializing in deciphering
            what users really mean when they ask questions. I excel at recognizing patterns, understanding
            context from conversations, and reformulating queries to get the best possible results.""",
        )

    def _initialize(self):
        """Initialize query processing components"""
        # Load spaCy model for NLP
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except Exception:
            logger.warning("spaCy model not found, using basic processing")
            self.nlp = None

        # Query templates for different intents
        self.query_templates = {
            "definition": ["what is", "define", "meaning of", "explain"],
            "comparison": ["difference between", "compare", "versus", "vs"],
            "procedure": ["how to", "steps to", "process for", "guide"],
            "location": ["where is", "location of", "find"],
            "temporal": ["when", "what time", "date of", "timeline"],
            "causal": ["why", "reason for", "cause of", "because"],
            "listing": ["list of", "examples of", "types of", "kinds of"],
            "quantitative": ["how many", "how much", "number of", "amount"],
        }

        # Abbreviation expansions
        self.abbreviations = {
            "docs": "documents",
            "info": "information",
            "mgmt": "management",
            "dept": "department",
            "req": "requirements",
            "spec": "specification",
            "impl": "implementation",
            "config": "configuration",
            "admin": "administration",
            "auth": "authentication",
        }

        # Conversation history
        self.conversation_memory: Dict[str, List[Dict]] = {}

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register Query Agent specific tools"""

        @tool("Analyze Query Intent")
        def analyze_intent(query: str) -> str:
            """Analyze and classify the intent behind a user query"""
            return self._analyze_query_intent(query)

        @tool("Enhance Query")
        def enhance_query(query: str, context: str = "") -> str:
            """Enhance query with synonyms, expansions, and context"""
            return self._enhance_query_terms(query, context)

        @tool("Generate Query Variations")
        def generate_variations(query: str, num_variations: int = 3) -> str:
            """Generate multiple variations of a query for better search coverage"""
            return self._generate_query_variations(query, num_variations)

        @tool("Extract Query Entities")
        def extract_entities(query: str) -> str:
            """Extract named entities and key concepts from query"""
            return self._extract_query_entities(query)

        self.register_tool(analyze_intent)
        self.register_tool(enhance_query)
        self.register_tool(generate_variations)
        self.register_tool(extract_entities)

    async def process(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """
        Process and enhance user query

        Input:
            - query: Raw user query
            - conversation_history: Previous conversation context
            - user_preferences: User-specific preferences

        Output:
            - original_query: Original user query
            - intent: Recognized intent
            - enhanced_query: Enhanced version of query
            - query_variations: List of query variations
            - entities: Extracted entities
            - context_requirements: Required context level
            - search_parameters: Optimized search parameters
        """
        try:
            query = input_data.get("query", "")
            if not query:
                raise ValueError("Query is required")

            # Get conversation history
            conv_history = self._get_conversation_history(context.conversation_id)

            # Analyze intent
            intent_analysis = await self.measure_operation(
                lambda: self._perform_intent_analysis(query, conv_history)
            )

            # Resolve contextual references
            resolved_query = await self.measure_operation(
                lambda: self._resolve_contextual_references(query, conv_history)
            )

            # Enhance query
            enhanced_query = await self.measure_operation(
                lambda: self._perform_query_enhancement(resolved_query, intent_analysis)
            )

            # Generate variations
            query_variations = await self.measure_operation(
                lambda: self._create_query_variations(enhanced_query, intent_analysis)
            )

            # Extract entities and concepts
            entities = await self.measure_operation(
                lambda: self._perform_entity_extraction(enhanced_query)
            )

            # Determine context requirements
            context_level = await self.measure_operation(
                lambda: self._determine_context_requirements(query, intent_analysis)
            )

            # Build search parameters
            search_params = await self.measure_operation(
                lambda: self._build_search_parameters(
                    enhanced_query, intent_analysis, entities, context_level
                )
            )

            # Update conversation memory
            self._update_conversation_memory(
                context.conversation_id, query, intent_analysis
            )

            return {
                "original_query": query,
                "resolved_query": resolved_query,
                "intent": intent_analysis,
                "enhanced_query": enhanced_query,
                "query_variations": query_variations,
                "entities": entities,
                "context_requirements": context_level,
                "search_parameters": search_params,
                "processing_metrics": {
                    "enhancement_ratio": len(enhanced_query) / len(query),
                    "variations_count": len(query_variations),
                    "entities_found": len(entities),
                    "processing_time_ms": self.metrics.average_latency,
                },
            }

        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            self.metrics.record_error()
            raise

    async def _perform_intent_analysis(
        self, query: str, conversation_history: List[Dict]
    ) -> Dict[str, Any]:
        """Analyze query intent using GPT-4 and pattern matching"""

        # Pattern-based intent detection
        pattern_intent = self._detect_pattern_based_intent(query.lower())

        # GPT-4 intent analysis
        prompt = f"""Analyze the intent of this query considering the conversation context:

Query: {query}

Recent conversation:
{self._format_conversation_history(conversation_history[-3:])}

Identify:
1. Primary intent (what the user wants to achieve)
2. Intent category (definition, comparison, procedure, etc.)
3. Urgency level (low, medium, high)
4. Scope (specific, broad, exploratory)
5. Expected response type (factual, analytical, instructional)

Provide analysis as JSON."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        gpt_intent = json.loads(response.choices[0].message.content)

        # Combine pattern and GPT analysis
        return {
            "pattern_intent": pattern_intent,
            "gpt_analysis": gpt_intent,
            "confidence": self._calculate_intent_confidence(pattern_intent, gpt_intent),
            "requires_context": self._requires_conversation_context(query),
        }

    def _detect_pattern_based_intent(self, query: str) -> Optional[str]:
        """Detect intent based on query patterns"""
        for intent_type, patterns in self.query_templates.items():
            for pattern in patterns:
                if pattern in query:
                    return intent_type
        return "general"

    async def _resolve_contextual_references(
        self, query: str, conversation_history: List[Dict]
    ) -> str:
        """Resolve pronouns and contextual references"""

        # Check for pronouns and references
        pronouns = ["it", "this", "that", "they", "them", "those", "these"]
        has_references = any(pronoun in query.lower().split() for pronoun in pronouns)

        if not has_references or not conversation_history:
            return query

        # Use GPT-4 to resolve references
        prompt = f"""Resolve contextual references in this query based on conversation history:

Query: {query}

Recent conversation:
{self._format_conversation_history(conversation_history[-3:])}

Rewrite the query with explicit references instead of pronouns.
Only return the rewritten query, nothing else."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        )

        return response.choices[0].message.content.strip()

    async def _perform_query_enhancement(
        self, query: str, intent_analysis: Dict[str, Any]
    ) -> str:
        """Enhance query with synonyms and expansions"""

        # Expand abbreviations
        enhanced = self._expand_abbreviations(query)

        # Add intent-specific enhancements
        intent_type = intent_analysis.get("pattern_intent", "general")

        enhancement_prompt = f"""Enhance this query for better search results:

Query: {enhanced}
Intent: {intent_type}

Enhancements to apply:
1. Add relevant synonyms
2. Include related technical terms
3. Expand concepts for comprehensive search
4. Maintain original meaning

Return only the enhanced query."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": enhancement_prompt}],
            temperature=0.2,
            max_tokens=150,
        )

        return response.choices[0].message.content.strip()

    def _expand_abbreviations(self, query: str) -> str:
        """Expand known abbreviations in query"""
        words = query.split()
        expanded_words = []

        for word in words:
            lower_word = word.lower()
            if lower_word in self.abbreviations:
                expanded_words.append(self.abbreviations[lower_word])
            else:
                expanded_words.append(word)

        return " ".join(expanded_words)

    async def _create_query_variations(
        self, query: str, intent_analysis: Dict[str, Any]
    ) -> List[str]:
        """Generate query variations for comprehensive search"""

        variations = [query]  # Original query

        # GPT-4 variations
        prompt = f"""Generate 3 variations of this query that would help find relevant information:

Query: {query}
Intent: {intent_analysis.get("pattern_intent", "general")}

Requirements:
1. Maintain the core meaning
2. Use different phrasings
3. Include related terms
4. Vary specificity levels

Return as JSON array of strings."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            response_format={"type": "json_object"},
        )

        try:
            result = json.loads(response.choices[0].message.content)
            if isinstance(result, dict) and "variations" in result:
                variations.extend(result["variations"])
            elif isinstance(result, list):
                variations.extend(result)
        except Exception:
            logger.warning("Failed to parse query variations")

        # Ensure uniqueness
        return list(set(variations))[:4]  # Limit to 4 variations

    async def _perform_entity_extraction(self, query: str) -> List[Dict[str, Any]]:
        """Extract entities and key concepts from query"""

        entities = []

        # Use spaCy if available
        if self.nlp:
            doc = self.nlp(query)
            for ent in doc.ents:
                entities.append(
                    {
                        "text": ent.text,
                        "type": ent.label_,
                        "start": ent.start_char,
                        "end": ent.end_char,
                    }
                )

        # GPT-4 entity extraction for better coverage
        prompt = f"""Extract entities and key concepts from this query:

Query: {query}

Extract:
1. Named entities (people, organizations, locations)
2. Technical terms
3. Time references
4. Numeric values
5. Key concepts

Return as JSON array with 'text', 'type', and 'importance' for each."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )

        try:
            result = json.loads(response.choices[0].message.content)
            if isinstance(result, dict) and "entities" in result:
                entities.extend(result["entities"])
            elif isinstance(result, list):
                entities.extend(result)
        except Exception:
            logger.warning("Failed to parse entities from GPT-4")

        # Remove duplicates
        seen = set()
        unique_entities = []
        for entity in entities:
            if entity["text"] not in seen:
                seen.add(entity["text"])
                unique_entities.append(entity)

        return unique_entities

    async def _determine_context_requirements(
        self, query: str, intent_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Determine required context level for query"""

        # Keywords indicating different context levels
        global_keywords = [
            "all",
            "everything",
            "across",
            "entire",
            "whole",
            "comprehensive",
        ]
        document_keywords = ["document", "file", "report", "in this", "within"]

        query_lower = query.lower()

        # Determine primary context level
        if any(keyword in query_lower for keyword in global_keywords):
            primary_level = "global"
        elif any(keyword in query_lower for keyword in document_keywords):
            primary_level = "document"
        else:
            primary_level = "local"

        # Determine if multi-level context is needed
        scope = intent_analysis.get("gpt_analysis", {}).get("scope", "specific")

        return {
            "primary_level": primary_level,
            "multi_level": scope == "broad" or scope == "exploratory",
            "levels": ["local", "document", "global"]
            if scope == "exploratory"
            else [primary_level],
            "confidence": 0.8 if primary_level != "local" else 0.9,
        }

    async def _build_search_parameters(
        self,
        query: str,
        intent: Dict[str, Any],
        entities: List[Dict],
        context_level: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build optimized search parameters"""

        # Base parameters
        params = {
            "query": query,
            "intent_type": intent.get("pattern_intent", "general"),
            "context_levels": context_level["levels"],
            "filters": {},
        }

        # Add entity-based filters
        for entity in entities:
            if entity.get("type") == "DATE":
                params["filters"]["temporal"] = entity["text"]
            elif entity.get("type") in ["ORG", "PERSON"]:
                params["filters"]["entities"] = params["filters"].get("entities", [])
                params["filters"]["entities"].append(entity["text"])

        # Add intent-specific parameters
        if intent.get("pattern_intent") == "comparison":
            params["require_multiple_results"] = True
            params["min_results"] = 2
        elif intent.get("pattern_intent") == "listing":
            params["require_multiple_results"] = True
            params["min_results"] = 5

        # Add ranking preferences
        urgency = intent.get("gpt_analysis", {}).get("urgency_level", "medium")
        if urgency == "high":
            params["boost_recent"] = True
            params["recency_weight"] = 0.3

        return params

    def _get_conversation_history(self, conversation_id: str) -> List[Dict]:
        """Get conversation history for context"""
        return self.conversation_memory.get(conversation_id, [])

    def _update_conversation_memory(
        self, conversation_id: str, query: str, intent: Dict[str, Any]
    ):
        """Update conversation memory with new query"""
        if conversation_id not in self.conversation_memory:
            self.conversation_memory[conversation_id] = []

        self.conversation_memory[conversation_id].append(
            {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "intent": intent.get("pattern_intent", "general"),
                "entities": intent.get("entities", []),
            }
        )

        # Keep only last 20 entries
        self.conversation_memory[conversation_id] = self.conversation_memory[
            conversation_id
        ][-20:]

    def _format_conversation_history(self, history: List[Dict]) -> str:
        """Format conversation history for prompts"""
        if not history:
            return "No previous conversation"

        formatted = []
        for entry in history:
            formatted.append(
                f"[{entry['timestamp']}] Query: {entry['query']} (Intent: {entry['intent']})"
            )

        return "\n".join(formatted)

    def _calculate_intent_confidence(
        self, pattern_intent: str, gpt_intent: Dict[str, Any]
    ) -> float:
        """Calculate confidence in intent detection"""
        # Simple confidence calculation
        if pattern_intent == gpt_intent.get("intent_category"):
            return 0.95
        elif pattern_intent != "general":
            return 0.8
        else:
            return 0.7

    def _requires_conversation_context(self, query: str) -> bool:
        """Check if query requires conversation context"""
        context_indicators = [
            "it",
            "this",
            "that",
            "they",
            "them",
            "the same",
            "similar",
            "like before",
            "as mentioned",
            "you said",
        ]

        query_lower = query.lower()
        return any(indicator in query_lower for indicator in context_indicators)

    # Tool method implementations
    def _analyze_query_intent(self, query: str) -> str:
        """Tool method for intent analysis"""
        intent = self._detect_pattern_based_intent(query.lower())
        return f"Query intent: {intent}"

    def _enhance_query_terms(self, query: str, context: str) -> str:
        """Tool method for query enhancement"""
        enhanced = self._expand_abbreviations(query)
        return f"Enhanced query: {enhanced}"

    def _generate_query_variations(self, query: str, num_variations: int) -> str:
        """Tool method for variation generation"""
        return f"Generated {num_variations} variations of: {query}"

    def _extract_query_entities(self, query: str) -> str:
        """Tool method for entity extraction"""
        # Simple entity extraction for tool
        entities = re.findall(r"\b[A-Z][a-z]+\b", query)
        return f"Entities found: {', '.join(entities)}"
