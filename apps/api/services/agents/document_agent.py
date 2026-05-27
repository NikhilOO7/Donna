# apps/api/services/agents/document_agent.py
"""
Document Agent - Handles document understanding and relationship mapping
Implements intelligent chunking, multi-level context extraction, and metadata enrichment
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import PyPDF2
import tiktoken
from crewai.tools import tool
from docx import Document as DocxDocument

from apps.api.services.agents.base_agent import AgentContext, BaseAgent
from apps.api.services.document.contextual_processor import ModernDocumentProcessor
from apps.api.services.document.embeddings import ContextualEmbeddingGenerator
from apps.api.services.document.processor import DocumentProcessor

logger = logging.getLogger(__name__)


class DocumentAgent(BaseAgent):
    """
    Document Agent - Super-intelligent speed reader that understands document relationships

    Responsibilities:
    - Document ingestion and intelligent chunking
    - Multi-level context extraction (local, document, global)
    - Metadata enrichment and tagging
    - Document relationship mapping
    - Structure preservation and hierarchy understanding
    """

    def __init__(self):
        super().__init__(
            name="document_agent",
            role="Document Intelligence Specialist",
            goal="Extract deep insights and structure from documents using advanced contextual understanding",
            backstory="""I am an expert in document analysis with years of experience in understanding
            complex document structures, extracting meaningful relationships, and preserving context
            at multiple levels. I excel at identifying how information connects within and across documents.""",
        )

    def _initialize(self):
        """Initialize document processing components"""
        self.doc_processor = DocumentProcessor()
        self.modern_processor = ModernDocumentProcessor()
        self.embedding_generator = ContextualEmbeddingGenerator()
        self.encoding = tiktoken.encoding_for_model("gpt-4")

        # Register tools
        self._register_tools()

    def _register_tools(self):
        """Register Document Agent specific tools"""

        @tool("Extract Document Structure")
        def extract_structure(document_path: str) -> str:
            """Extract and analyze document structure including sections, headings, and hierarchy"""
            return self._extract_document_structure(document_path)

        @tool("Identify Document Relationships")
        def identify_relationships(doc1_id: str, doc2_id: str) -> str:
            """Identify relationships and references between two documents"""
            return self._identify_document_relationships(doc1_id, doc2_id)

        @tool("Generate Document Metadata")
        def generate_metadata(document_content: str) -> str:
            """Generate rich metadata including topics, entities, and categories"""
            return self._generate_document_metadata(document_content)

        @tool("Extract Contextual Chunks")
        def extract_chunks(document_path: str, chunk_size: int = 1000) -> str:
            """Extract semantically meaningful chunks preserving context"""
            return self._extract_contextual_chunks(document_path, chunk_size)

        self.register_tool(extract_structure)
        self.register_tool(identify_relationships)
        self.register_tool(generate_metadata)
        self.register_tool(extract_chunks)

    async def process(
        self, input_data: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """
        Main document processing pipeline

        Input:
            - document_path: Path to document
            - document_type: Type of document (pdf, docx, txt, md)
            - processing_options: Additional processing options

        Output:
            - document_id: Unique document identifier
            - chunks: List of contextual chunks with embeddings
            - metadata: Enriched document metadata
            - structure: Document structure analysis
            - relationships: Identified relationships
        """
        try:
            document_path = input_data.get("document_path")
            if not document_path:
                raise ValueError("Document path is required")

            # Extract raw content
            raw_content = await self.measure_operation(
                lambda: self._extract_raw_content(document_path)
            )

            # Generate document ID
            doc_id = self._generate_document_id(raw_content)

            # Extract document structure
            structure = await self.measure_operation(
                lambda: self._analyze_document_structure(raw_content)
            )

            # Create contextual chunks
            chunks = await self.measure_operation(
                lambda: self._create_contextual_chunks(raw_content, structure)
            )

            # Generate multi-level embeddings
            embeddings = await self.measure_operation(
                lambda: self._generate_contextual_embeddings(chunks, doc_id)
            )

            # Extract metadata
            metadata = await self.measure_operation(
                lambda: self._extract_comprehensive_metadata(raw_content, structure)
            )

            # Identify relationships
            relationships = await self.measure_operation(
                lambda: self._map_document_relationships(raw_content, context)
            )

            # Store in context
            context.metadata[f"doc_{doc_id}_processed"] = datetime.now()

            return {
                "document_id": doc_id,
                "chunks": chunks,
                "embeddings": embeddings,
                "metadata": metadata,
                "structure": structure,
                "relationships": relationships,
                "processing_metrics": {
                    "chunk_count": len(chunks),
                    "avg_chunk_size": sum(len(c["content"]) for c in chunks)
                    / len(chunks)
                    if chunks
                    else 0,
                    "processing_time_ms": self.metrics.average_latency,
                },
            }

        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            self.metrics.record_error()
            raise

    async def _extract_raw_content(self, document_path: str) -> Dict[str, Any]:
        """Extract raw content from document"""
        path = Path(document_path)
        content = ""

        if path.suffix.lower() == ".pdf":
            content = await self._extract_pdf_content(path)
        elif path.suffix.lower() in [".docx", ".doc"]:
            content = await self._extract_docx_content(path)
        elif path.suffix.lower() in [".txt", ".md"]:
            content = path.read_text(encoding="utf-8")
        else:
            raise ValueError(f"Unsupported document type: {path.suffix}")

        return {
            "content": content,
            "file_type": path.suffix.lower(),
            "file_name": path.name,
            "file_size": path.stat().st_size,
        }

    async def _extract_pdf_content(self, path: Path) -> str:
        """Extract text content from PDF"""
        content = []
        with open(path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                content.append(page.extract_text())
        return "\n".join(content)

    async def _extract_docx_content(self, path: Path) -> str:
        """Extract text content from DOCX"""
        doc = DocxDocument(path)
        content = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                content.append(paragraph.text)
        return "\n".join(content)

    async def _analyze_document_structure(
        self, raw_content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze document structure and hierarchy"""
        content = raw_content["content"]

        # Use GPT-4 to analyze structure
        prompt = f"""Analyze the structure of this document and identify:
        1. Main sections and subsections
        2. Document hierarchy
        3. Key structural elements (headings, lists, tables mentions)
        4. Document flow and organization

        Document excerpt (first 2000 chars):
        {content[:2000]}

        Provide analysis in JSON format."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        structure = json.loads(response.choices[0].message.content)

        # Add token count information
        structure["token_count"] = len(self.encoding.encode(content))
        structure["estimated_pages"] = len(content) / 3000  # Rough estimate

        return structure

    async def _create_contextual_chunks(
        self, raw_content: Dict[str, Any], structure: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Create intelligent chunks preserving semantic boundaries"""
        content = raw_content["content"]
        chunks = []

        # Split content into paragraphs first
        paragraphs = content.split("\n\n")

        current_chunk = ""
        current_section = ""
        chunk_index = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Check if this is a section header (simple heuristic)
            if len(para) < 100 and (para.isupper() or para.endswith(":")):
                # Save current chunk if exists
                if current_chunk:
                    chunks.append(
                        {
                            "index": chunk_index,
                            "content": current_chunk.strip(),
                            "section": current_section,
                            "type": "content",
                            "token_count": len(self.encoding.encode(current_chunk)),
                        }
                    )
                    chunk_index += 1
                    current_chunk = ""

                current_section = para

            # Check if adding this paragraph would exceed token limit
            temp_chunk = current_chunk + "\n\n" + para if current_chunk else para
            token_count = len(self.encoding.encode(temp_chunk))

            if token_count > 800:  # Leave room for context
                # Save current chunk
                chunks.append(
                    {
                        "index": chunk_index,
                        "content": current_chunk.strip(),
                        "section": current_section,
                        "type": "content",
                        "token_count": len(self.encoding.encode(current_chunk)),
                    }
                )
                chunk_index += 1
                current_chunk = para
            else:
                current_chunk = temp_chunk

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(
                {
                    "index": chunk_index,
                    "content": current_chunk.strip(),
                    "section": current_section,
                    "type": "content",
                    "token_count": len(self.encoding.encode(current_chunk)),
                }
            )

        # Add chunk relationships
        for i, chunk in enumerate(chunks):
            chunk["prev_chunk"] = i - 1 if i > 0 else None
            chunk["next_chunk"] = i + 1 if i < len(chunks) - 1 else None
            chunk["chunk_id"] = f"{raw_content['file_name']}_{i}"

        return chunks

    async def _generate_contextual_embeddings(
        self, chunks: List[Dict[str, Any]], doc_id: str
    ) -> Dict[str, List[float]]:
        """Generate multi-level contextual embeddings"""
        embeddings = {}

        for chunk in chunks:
            # Local context embedding (just the chunk)
            local_embedding = await self.embedding_generator.generate_embedding(
                chunk["content"]
            )

            # Document context embedding (chunk + surrounding context)
            doc_context = self._get_document_context(chunk, chunks)
            doc_embedding = await self.embedding_generator.generate_embedding(
                doc_context
            )

            # Global context embedding (chunk + document summary)
            global_context = self._get_global_context(chunk, chunks, doc_id)
            global_embedding = await self.embedding_generator.generate_embedding(
                global_context
            )

            embeddings[chunk["chunk_id"]] = {
                "local": local_embedding,
                "document": doc_embedding,
                "global": global_embedding,
            }

        return embeddings

    def _get_document_context(
        self, chunk: Dict[str, Any], all_chunks: List[Dict[str, Any]]
    ) -> str:
        """Get document-level context for a chunk"""
        context_parts = []

        # Add section information
        if chunk.get("section"):
            context_parts.append(f"Section: {chunk['section']}")

        # Add previous chunk summary
        if chunk["prev_chunk"] is not None:
            prev_chunk = all_chunks[chunk["prev_chunk"]]
            context_parts.append(f"Previous context: {prev_chunk['content'][:200]}...")

        # Add the chunk itself
        context_parts.append(f"Current content: {chunk['content']}")

        # Add next chunk preview
        if chunk["next_chunk"] is not None:
            next_chunk = all_chunks[chunk["next_chunk"]]
            context_parts.append(f"Following context: {next_chunk['content'][:200]}...")

        return "\n\n".join(context_parts)

    def _get_global_context(
        self, chunk: Dict[str, Any], all_chunks: List[Dict[str, Any]], doc_id: str
    ) -> str:
        """Get global context including document summary"""
        # Create a simple document summary from first and last chunks
        doc_summary = f"Document {doc_id} summary:\n"
        if all_chunks:
            doc_summary += f"Beginning: {all_chunks[0]['content'][:300]}...\n"
            if len(all_chunks) > 1:
                doc_summary += f"Ending: {all_chunks[-1]['content'][:300]}..."

        return f"{doc_summary}\n\nSpecific section:\n{chunk['content']}"

    async def _extract_comprehensive_metadata(
        self, raw_content: Dict[str, Any], structure: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract comprehensive metadata using GPT-4"""
        content_sample = raw_content["content"][:3000]  # First 3000 chars

        prompt = f"""Extract comprehensive metadata from this document:

{content_sample}

Extract:
1. Main topics and themes
2. Document type and category
3. Key entities (people, organizations, locations)
4. Temporal references (dates, time periods)
5. Document purpose and audience
6. Technical level and domain
7. Keywords (10-15 most important)

Provide as JSON."""

        response = await self.openai_client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        metadata = json.loads(response.choices[0].message.content)

        # Add file metadata
        metadata.update(
            {
                "file_name": raw_content["file_name"],
                "file_type": raw_content["file_type"],
                "file_size": raw_content["file_size"],
                "processed_date": datetime.now().isoformat(),
                "structure_summary": structure,
            }
        )

        return metadata

    async def _map_document_relationships(
        self, raw_content: Dict[str, Any], context: AgentContext
    ) -> Dict[str, Any]:
        """Map relationships to other documents using vector similarity + GPT-4.

        Strategy 1: Vector search for semantically similar chunks in other documents.
        Strategy 2: GPT-4 analysis for explicit references and thematic connections.
        """
        content = raw_content["content"][:2000]
        current_doc_id = context.metadata.get("document_id", "")

        relationships = {
            "related_documents": [],
            "shared_topics": [],
            "references": [],
        }

        # Strategy 1: Vector similarity search for related documents
        try:
            from apps.api.core.config import settings
            from apps.api.core.connections import get_qdrant_client
            from apps.api.services.document.embeddings import (
                ContextualEmbeddingGenerator,
            )

            embedding_gen = ContextualEmbeddingGenerator()
            snippet = content[:500]
            emb_result = await embedding_gen._generate_embedding(
                snippet, use_voyage=False
            )
            query_vector = emb_result.get("openai") or emb_result.get("local")

            if query_vector:
                client = await get_qdrant_client()
                if client:
                    collection = f"{settings.qdrant_collection_name}_unified"
                    try:
                        results = await client.search(
                            collection_name=collection,
                            query_vector=query_vector,
                            limit=10,
                            with_payload=True,
                            with_vectors=False,
                        )

                        doc_scores: Dict[str, float] = {}
                        doc_snippets: Dict[str, list] = {}
                        for r in results:
                            doc_id = r.payload.get("document_id", "")
                            if doc_id and doc_id != current_doc_id and r.score > 0.5:
                                if (
                                    doc_id not in doc_scores
                                    or r.score > doc_scores[doc_id]
                                ):
                                    doc_scores[doc_id] = r.score
                                if doc_id not in doc_snippets:
                                    doc_snippets[doc_id] = []
                                doc_snippets[doc_id].append(
                                    r.payload.get("content", "")[:100]
                                )

                        for doc_id, score in sorted(
                            doc_scores.items(), key=lambda x: -x[1]
                        )[:5]:
                            relationships["related_documents"].append(
                                {
                                    "document_id": doc_id,
                                    "similarity_score": round(score, 3),
                                    "matching_snippets": doc_snippets.get(doc_id, [])[
                                        :2
                                    ],
                                }
                            )
                    except Exception:
                        pass  # Collection may not exist yet
        except Exception as e:
            logger.debug(f"Vector relationship search failed: {e}")

        # Strategy 2: GPT-4 analysis for explicit references
        try:
            prompt = f"""Analyze this text and identify:
1. Direct references to other documents (e.g. "as described in the safety manual")
2. Key topics/themes that could connect to other documents
Return JSON with keys: "references" (list of strings), "shared_topics" (list of strings)

Text:
{content[:1000]}"""

            response = await self.openai_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            gpt_result = json.loads(response.choices[0].message.content)
            relationships["references"] = gpt_result.get("references", [])
            relationships["shared_topics"] = gpt_result.get("shared_topics", [])
        except Exception as e:
            logger.debug(f"GPT-4 relationship analysis failed: {e}")

        relationships["conversation_context"] = {
            "conversation_id": context.conversation_id,
            "related_queries": context.metadata.get("queries", []),
        }

        return relationships

    def _generate_document_id(self, raw_content: Dict[str, Any]) -> str:
        """Generate unique document ID"""
        # Create hash from content
        content_hash = hashlib.sha256(raw_content["content"].encode()).hexdigest()[:12]
        return f"{raw_content['file_name']}_{content_hash}"

    def _extract_document_structure(self, document_path: str) -> str:
        """Tool method for structure extraction"""
        # This would be implemented to work with the tool framework
        return f"Structure extraction for {document_path}"

    def _identify_document_relationships(self, doc1_id: str, doc2_id: str) -> str:
        """Tool method for relationship identification"""
        return f"Relationships between {doc1_id} and {doc2_id}"

    def _generate_document_metadata(self, document_content: str) -> str:
        """Tool method for metadata generation"""
        return f"Metadata for document with {len(document_content)} characters"

    def _extract_contextual_chunks(self, document_path: str, chunk_size: int) -> str:
        """Tool method for chunk extraction"""
        return f"Extracted chunks from {document_path} with size {chunk_size}"
