# ADR-001: Three-Level Contextual Embedding Architecture

## Status
Accepted

## Context
Traditional RAG systems embed each document chunk in isolation, losing context about where the chunk sits within the document structure and how it relates to other documents. This leads to poor retrieval for queries that require understanding relationships, section hierarchy, or cross-document themes.

We needed an embedding strategy that captures meaning at multiple granularities while remaining cost-effective with external embedding APIs.

## Decision
We implement a **three-level contextual embedding** approach:

1. **Local Context (50% weight)** - Each chunk is embedded with its neighboring chunks' content prepended. This preserves paragraph-level coherence.
2. **Document Context (30% weight)** - Each chunk is embedded with document-level metadata (title, section path, key topics). This preserves structural awareness.
3. **Global Context (20% weight)** - Each chunk is embedded with cross-document relationship signals. This enables thematic connections across the corpus.

Embeddings are generated via OpenAI `text-embedding-3-small` (1536 dimensions) and stored in **four separate Qdrant collections** (local, document, global, unified) to enable context-specific retrieval.

## Consequences
- **Positive**: Significantly better retrieval relevance for structural and relational queries. Multi-level search enables both precise and exploratory queries.
- **Positive**: The unified collection provides a fallback for simple queries without the complexity of multi-collection search.
- **Negative**: 4x storage cost in Qdrant (four collections per embedding).
- **Negative**: Document processing is ~3x slower due to multiple embedding calls per chunk.
- **Mitigated**: Embedding caching (in-memory hash-based) reduces redundant API calls during batch processing.
