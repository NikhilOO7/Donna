# apps/api/services/agents/context_agent.py
"""
Context Agent - Manages contextual search strategies and multi-factor ranking
Smart search engine that understands meaning and finds truly relevant information
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import networkx as nx
from crewai.tools import tool

from apps.api.services.agents.base_agent import AgentContext, BaseAgent
from apps.api.services.document.embeddings import ContextualEmbeddingGenerator
from apps.api.services.document.vector_store import ModernVectorStore

logger = logging.getLogger(__name__)


class ContextAgent(BaseAgent):
    """
    Context Agent - Smart search engine with contextual understanding

    Responsibilities:
    - Contextual embeddings search (local, document, global)
    - Hybrid search strategies (semantic + keyword + metadata)
    - Multi-factor ranking and relevance scoring
    - Context expansion and related content discovery
    - Hierarchical retrieval respecting document structure
    """

    def __init__(self):
        super().__init__(
            name="context_agent",
            role="Contextual Search Specialist",
            goal="Find truly relevant information by understanding meaning and context at multiple levels",
            backstory="""I am an expert in information retrieval with deep understanding of semantic search,
            contextual embeddings, and relevance ranking. I excel at finding not just matching words but
            truly relevant information by understanding the deeper meaning and context of queries.""",
        )

    def _initialize(self):
        """Initialize context search components"""
        self.vector_store = ModernVectorStore()
        self.embedding_generator = ContextualEmbeddingGenerator()

        # Search configuration
        self.search_config = {
            "semantic_weight": 0.7,
            "keyword_weight": 0.2,
            "metadata_weight": 0.1,
            "recency_decay": 0.05,  # Daily decay factor
            "authority_boost": 1.2,  # Boost for authoritative sources
            "context_expansion_limit": 3,  # Max related chunks to include
        }

        # Document graph for relationship-based retrieval
        self.document_graph = nx.DiGraph()

        # Cache for search results
        self.search_cache: Dict[str, Dict] = {}
        self.cache_ttl = 300  # 5 minutes

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register Context Agent specific tools"""

        @tool("Semantic Search")
        def semantic_search(query: str, top_k: int = 10) -> str:
            """Perform semantic search using contextual embeddings"""
            return self._perform_semantic_search(query, top_k)

        @tool("Hybrid Search")
        def hybrid_search(query: str, filters: Dict = None) -> str:
            """Perform hybrid search combining semantic, keyword, and metadata"""
            return self._perform_hybrid_search(query, filters or {})

        @tool("Context Expansion")
        def expand_context(chunk_id: str, expansion_type: str = "related") -> str:
            """Expand context by finding related content"""
            return self._expand_context(chunk_id, expansion_type)

        @tool("Rank Results")
        def rank_results(results: List[Dict], query: str) -> str:
            """Apply multi-factor ranking to search results"""
            return self._rank_search_results(results, query)

        self.register_tool(semantic_search)
        self.register_tool(hybrid_search)
        self.register_tool(expand_context)
        self.register_tool(rank_results)

    async def process(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """
        Perform contextual search and retrieval

        Input:
            - query: Search query (enhanced by Query Agent)
            - context_levels: Required context levels (local, document, global)
            - filters: Search filters (metadata, temporal, etc.)
            - search_parameters: Additional search parameters

        Output:
            - results: Ranked search results with context
            - expanded_results: Additional related content
            - search_metrics: Search performance metrics
            - context_graph: Relationship graph of results
        """
        try:
            query = input_data.get("query", "")
            context_levels = input_data.get("context_levels", ["local"])
            filters = input_data.get("filters", {})
            search_params = input_data.get("search_parameters", {})

            # Check cache first
            cache_key = self._generate_cache_key(query, context_levels, filters)
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                logger.info(f"Returning cached result for query: {query}")
                return cached_result

            # Generate query embeddings for each context level
            query_embeddings = await self.measure_operation(
                lambda: self._generate_multi_level_embeddings(query, context)
            )

            # Perform multi-level search
            raw_results = await self.measure_operation(
                lambda: self._perform_multi_level_search(
                    query_embeddings, context_levels, filters
                )
            )

            # Apply hybrid scoring
            scored_results = await self.measure_operation(
                lambda: self._apply_hybrid_scoring(raw_results, query, query_embeddings)
            )

            # Rank results with multi-factor algorithm
            ranked_results = await self.measure_operation(
                lambda: self._apply_multi_factor_ranking(scored_results, search_params)
            )

            # Expand context for top results
            expanded_results = await self.measure_operation(
                lambda: self._expand_top_results_context(
                    ranked_results[:5], context_levels
                )
            )

            # Build context graph
            context_graph = await self.measure_operation(
                lambda: self._build_context_graph(ranked_results, expanded_results)
            )

            # Prepare final results
            result = {
                "results": ranked_results,
                "expanded_results": expanded_results,
                "context_graph": context_graph,
                "search_metrics": {
                    "total_candidates": len(raw_results),
                    "filtered_results": len(scored_results),
                    "final_results": len(ranked_results),
                    "expansion_count": len(expanded_results),
                    "context_levels_searched": context_levels,
                    "processing_time_ms": self.metrics.average_latency,
                },
            }

            # Cache the result
            self._cache_result(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"Context search failed: {e}")
            self.metrics.record_error()
            raise

    async def _generate_multi_level_embeddings(
        self, query: str, agent_context: AgentContext
    ) -> Dict[str, List[float]]:
        """Generate embeddings for different context levels"""
        embeddings = {}

        # Local context embedding (just the query)
        embeddings["local"] = await self.embedding_generator.generate_embedding(query)

        # Document context embedding (query + conversation context)
        if agent_context.metadata.get("current_document"):
            doc_context = f"Document: {agent_context.metadata['current_document']}\nQuery: {query}"
            embeddings["document"] = await self.embedding_generator.generate_embedding(
                doc_context
            )
        else:
            embeddings["document"] = embeddings["local"]

        # Global context embedding (query + all context)
        conversation_summary = self._summarize_conversation(agent_context)
        global_context = f"Context: {conversation_summary}\nQuery: {query}"
        embeddings["global"] = await self.embedding_generator.generate_embedding(
            global_context
        )

        return embeddings

    async def _perform_multi_level_search(
        self,
        query_embeddings: Dict[str, List[float]],
        context_levels: List[str],
        filters: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Perform search at multiple context levels"""
        all_results = []

        for level in context_levels:
            if level not in query_embeddings:
                continue

            # Search in vector store
            level_results = await self.vector_store.search(
                query_embedding=query_embeddings[level],
                top_k=20,  # Get more candidates for ranking
                filters=self._build_vector_filters(filters, level),
            )

            # Add context level metadata
            for result in level_results:
                result["context_level"] = level
                result["embedding_type"] = f"{level}_embedding"

            all_results.extend(level_results)

        # Remove duplicates while preserving best scores
        unique_results = {}
        for result in all_results:
            chunk_id = result.get("chunk_id")
            if (
                chunk_id not in unique_results
                or result["score"] > unique_results[chunk_id]["score"]
            ):
                unique_results[chunk_id] = result

        return list(unique_results.values())

    async def _apply_hybrid_scoring(
        self,
        results: List[Dict[str, Any]],
        query: str,
        query_embeddings: Dict[str, List[float]],
    ) -> List[Dict[str, Any]]:
        """Apply hybrid scoring combining semantic, keyword, and metadata scores"""

        scored_results = []
        query_terms = set(query.lower().split())

        for result in results:
            # Semantic score (from vector search)
            semantic_score = result.get("score", 0)

            # Keyword score
            content_lower = result.get("content", "").lower()
            keyword_matches = sum(1 for term in query_terms if term in content_lower)
            keyword_score = keyword_matches / len(query_terms) if query_terms else 0

            # Metadata score
            metadata_score = self._calculate_metadata_score(result, query)

            # Recency score
            recency_score = self._calculate_recency_score(result)

            # Authority score
            authority_score = self._calculate_authority_score(result)

            # Combined score
            hybrid_score = (
                (
                    self.search_config["semantic_weight"] * semantic_score
                    + self.search_config["keyword_weight"] * keyword_score
                    + self.search_config["metadata_weight"] * metadata_score
                )
                * recency_score
                * authority_score
            )

            result["scores"] = {
                "semantic": semantic_score,
                "keyword": keyword_score,
                "metadata": metadata_score,
                "recency": recency_score,
                "authority": authority_score,
                "hybrid": hybrid_score,
            }
            result["final_score"] = hybrid_score

            scored_results.append(result)

        return scored_results

    async def _apply_multi_factor_ranking(
        self, results: List[Dict[str, Any]], search_params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply sophisticated multi-factor ranking"""

        # Initial sort by hybrid score
        ranked = sorted(results, key=lambda x: x["final_score"], reverse=True)

        # Apply additional ranking factors
        if search_params.get("boost_recent"):
            # Re-rank with recency boost
            recency_weight = search_params.get("recency_weight", 0.3)
            for result in ranked:
                result["final_score"] *= (
                    1 + recency_weight * result["scores"]["recency"]
                )
            ranked = sorted(ranked, key=lambda x: x["final_score"], reverse=True)

        # Apply diversity ranking if multiple results requested
        if search_params.get("require_multiple_results"):
            ranked = self._apply_diversity_ranking(ranked)

        # Apply hierarchical ranking
        ranked = self._apply_hierarchical_ranking(ranked)

        # Limit results
        max_results = search_params.get("max_results", 10)
        return ranked[:max_results]

    def _apply_diversity_ranking(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Ensure diversity in results"""
        diverse_results = []
        seen_documents = set()
        seen_sections = set()

        for result in results:
            doc_id = result.get("document_id", "")
            section = result.get("section", "")

            # Prioritize different documents
            if doc_id not in seen_documents:
                diverse_results.append(result)
                seen_documents.add(doc_id)
            # Then different sections within same document
            elif f"{doc_id}:{section}" not in seen_sections:
                diverse_results.append(result)
                seen_sections.add(f"{doc_id}:{section}")
            # Include if score is significantly high
            elif result["final_score"] > 0.8:
                diverse_results.append(result)

        return diverse_results

    def _apply_hierarchical_ranking(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Apply hierarchical ranking respecting document structure"""

        # Group by document
        doc_groups = defaultdict(list)
        for result in results:
            doc_groups[result.get("document_id", "unknown")].append(result)

        # Rank within each document respecting hierarchy
        hierarchical_results = []

        for doc_id, doc_results in doc_groups.items():
            # Sort by section order if available
            doc_results.sort(
                key=lambda x: (x.get("section_order", 999), -x["final_score"])
            )
            hierarchical_results.extend(doc_results)

        return hierarchical_results

    async def _expand_top_results_context(
        self, top_results: List[Dict[str, Any]], context_levels: List[str]
    ) -> List[Dict[str, Any]]:
        """Expand context for top results"""
        expanded = []

        for result in top_results:
            # Get surrounding chunks
            surrounding = await self._get_surrounding_chunks(
                result.get("chunk_id"),
                result.get("document_id"),
                radius=self.search_config["context_expansion_limit"],
            )

            # Get related chunks from other documents
            related = await self._get_related_chunks(result, context_levels, limit=2)

            expanded.extend(surrounding)
            expanded.extend(related)

        # Remove duplicates
        unique_expanded = {}
        for chunk in expanded:
            chunk_id = chunk.get("chunk_id")
            if chunk_id not in unique_expanded:
                unique_expanded[chunk_id] = chunk

        return list(unique_expanded.values())

    async def _get_surrounding_chunks(
        self, chunk_id: str, document_id: str, radius: int = 2
    ) -> List[Dict[str, Any]]:
        """Get surrounding chunks from the same document"""
        surrounding = []

        # Extract chunk index from ID
        try:
            chunk_index = int(chunk_id.split("_")[-1])
        except Exception:
            return surrounding

        # Get previous and next chunks
        for offset in range(-radius, radius + 1):
            if offset == 0:  # Skip the original chunk
                continue

            target_index = chunk_index + offset
            if target_index < 0:
                continue

            # Search for the specific chunk
            neighbor_id = f"{document_id}_{target_index}"
            neighbor = await self.vector_store.get_chunk_by_id(neighbor_id)

            if neighbor:
                neighbor["relationship"] = "surrounding"
                neighbor["offset"] = offset
                surrounding.append(neighbor)

        return surrounding

    async def _get_related_chunks(
        self, source_chunk: Dict[str, Any], context_levels: List[str], limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Get related chunks from other documents"""
        related = []

        # Use the chunk's embedding to find similar content
        chunk_embedding = source_chunk.get("embedding")
        if not chunk_embedding:
            return related

        # Search for similar chunks in other documents
        similar = await self.vector_store.search(
            query_embedding=chunk_embedding,
            top_k=limit + 1,  # +1 to exclude self
            filters={"exclude_document": source_chunk.get("document_id")},
        )

        for chunk in similar:
            if chunk.get("chunk_id") != source_chunk.get("chunk_id"):
                chunk["relationship"] = "related"
                chunk["source_chunk"] = source_chunk.get("chunk_id")
                related.append(chunk)

        return related[:limit]

    async def _build_context_graph(
        self, results: List[Dict[str, Any]], expanded_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build a graph representing relationships between results"""

        # Create or clear graph
        graph = nx.DiGraph()

        # Add main results as nodes
        for result in results:
            graph.add_node(
                result["chunk_id"],
                type="primary",
                score=result["final_score"],
                content_preview=result.get("content", "")[:100],
                document_id=result.get("document_id"),
            )

        # Add expanded results as nodes
        for result in expanded_results:
            graph.add_node(
                result["chunk_id"],
                type="expanded",
                relationship=result.get("relationship", "unknown"),
                content_preview=result.get("content", "")[:100],
                document_id=result.get("document_id"),
            )

        # Add edges based on relationships
        for result in expanded_results:
            if result.get("source_chunk"):
                graph.add_edge(
                    result["source_chunk"],
                    result["chunk_id"],
                    relationship=result.get("relationship", "related"),
                )
            elif result.get("offset"):
                # Surrounding chunks
                for primary in results:
                    if primary.get("document_id") == result.get("document_id"):
                        graph.add_edge(
                            primary["chunk_id"],
                            result["chunk_id"],
                            relationship="surrounding",
                            offset=result["offset"],
                        )

        # Convert to serializable format
        return {
            "nodes": [{"id": node, **graph.nodes[node]} for node in graph.nodes()],
            "edges": [
                {"source": edge[0], "target": edge[1], **graph.edges[edge]}
                for edge in graph.edges()
            ],
            "statistics": {
                "total_nodes": graph.number_of_nodes(),
                "total_edges": graph.number_of_edges(),
                "connected_components": nx.number_weakly_connected_components(graph),
            },
        }

    def _calculate_metadata_score(self, result: Dict[str, Any], query: str) -> float:
        """Calculate score based on metadata matches"""
        score = 0.0
        metadata = result.get("metadata", {})
        query_lower = query.lower()

        # Check title match
        if metadata.get("title"):
            title_lower = metadata["title"].lower()
            if query_lower in title_lower:
                score += 0.5
            elif any(term in title_lower for term in query_lower.split()):
                score += 0.3

        # Check category/type match
        if metadata.get("category"):
            if metadata["category"].lower() in query_lower:
                score += 0.2

        # Check tag matches
        tags = metadata.get("tags", [])
        matching_tags = sum(1 for tag in tags if tag.lower() in query_lower)
        score += min(matching_tags * 0.1, 0.3)

        return min(score, 1.0)

    def _calculate_recency_score(self, result: Dict[str, Any]) -> float:
        """Calculate score based on document recency"""
        metadata = result.get("metadata", {})

        # Get document date
        doc_date_str = metadata.get("created_date") or metadata.get("modified_date")
        if not doc_date_str:
            return 1.0  # Neutral score if no date

        try:
            doc_date = datetime.fromisoformat(doc_date_str)
            days_old = (datetime.now() - doc_date).days

            # Apply decay factor
            decay_factor = self.search_config["recency_decay"]
            recency_score = max(0.5, 1.0 - (days_old * decay_factor))

            return recency_score
        except Exception:
            return 1.0

    def _calculate_authority_score(self, result: Dict[str, Any]) -> float:
        """Calculate score based on document authority"""
        metadata = result.get("metadata", {})

        # Authority indicators
        authority_score = 1.0

        # Document type authority
        doc_type = metadata.get("document_type", "").lower()
        if doc_type in ["policy", "standard", "regulation", "official"]:
            authority_score *= self.search_config["authority_boost"]
        elif doc_type in ["draft", "proposal", "unofficial"]:
            authority_score *= 0.8

        # Source authority
        source = metadata.get("source", "").lower()
        if any(auth in source for auth in ["official", "corporate", "legal"]):
            authority_score *= 1.1

        return min(authority_score, 2.0)  # Cap the boost

    def _build_vector_filters(
        self, filters: Dict[str, Any], context_level: str
    ) -> Dict[str, Any]:
        """Build filters for vector store search"""
        vector_filters = {}

        # Add temporal filters
        if filters.get("temporal"):
            vector_filters["date_range"] = filters["temporal"]

        # Add entity filters
        if filters.get("entities"):
            vector_filters["entities"] = filters["entities"]

        # Add context level filter
        vector_filters["embedding_level"] = context_level

        # Add document type filters
        if filters.get("document_types"):
            vector_filters["document_type"] = filters["document_types"]

        return vector_filters

    def _summarize_conversation(self, context: AgentContext) -> str:
        """Create a summary of the conversation context"""
        # Get recent queries from metadata
        recent_queries = context.metadata.get("recent_queries", [])
        if not recent_queries:
            return "General search context"

        # Create simple summary
        summary_parts = ["Previous queries:"]
        for query in recent_queries[-3:]:  # Last 3 queries
            summary_parts.append(f"- {query}")

        return " ".join(summary_parts)

    def _generate_cache_key(
        self, query: str, context_levels: List[str], filters: Dict[str, Any]
    ) -> str:
        """Generate cache key for search results"""
        # Create a deterministic key
        key_parts = [
            query.lower(),
            ",".join(sorted(context_levels)),
            json.dumps(filters, sort_keys=True),
        ]

        import hashlib

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get cached search result if available and not expired"""
        if cache_key not in self.search_cache:
            return None

        cached = self.search_cache[cache_key]
        cache_time = cached.get("timestamp", 0)

        # Check if cache is expired
        if (datetime.now().timestamp() - cache_time) > self.cache_ttl:
            del self.search_cache[cache_key]
            return None

        return cached.get("result")

    def _cache_result(self, cache_key: str, result: Dict[str, Any]):
        """Cache search result"""
        self.search_cache[cache_key] = {
            "result": result,
            "timestamp": datetime.now().timestamp(),
        }

        # Clean old cache entries
        self._clean_cache()

    def _clean_cache(self):
        """Remove expired cache entries"""
        current_time = datetime.now().timestamp()
        expired_keys = [
            key
            for key, value in self.search_cache.items()
            if (current_time - value.get("timestamp", 0)) > self.cache_ttl
        ]

        for key in expired_keys:
            del self.search_cache[key]

    # Tool method implementations
    def _perform_semantic_search(self, query: str, top_k: int) -> str:
        """Tool method for semantic search"""
        return f"Semantic search for '{query}' with top {top_k} results"

    def _perform_hybrid_search(self, query: str, filters: Dict[str, Any]) -> str:
        """Tool method for hybrid search"""
        return f"Hybrid search for '{query}' with filters: {filters}"

    def _expand_context(self, chunk_id: str, expansion_type: str) -> str:
        """Tool method for context expansion"""
        return (
            f"Expanding context for chunk {chunk_id} using {expansion_type} expansion"
        )

    def _rank_search_results(self, results: List[Dict], query: str) -> str:
        """Tool method for result ranking"""
        return f"Ranking {len(results)} results for query: {query}"
