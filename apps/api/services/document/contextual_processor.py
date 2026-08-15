# apps/api/services/document/contextual_processor.py
"""
Enhanced Document Processor with 3-level Contextual Embeddings
Implements intelligent chunking and multi-level context extraction
"""

import hashlib
import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Document processing
import docx
import nltk
import spacy
import tiktoken
from nltk.corpus import stopwords
from nltk.tokenize import sent_tokenize, word_tokenize
from pdfplumber import PDF

# ML/NLP
from sentence_transformers import SentenceTransformer

# Your imports
from apps.api.core import llm_provider

logger = logging.getLogger(__name__)


# Download required NLTK data
def download_nltk_data():
    """Download NLTK data packages (SSL certificates properly installed)"""
    import os

    # Ensure NLTK data directory exists
    nltk_data_dir = os.path.expanduser("~/nltk_data")
    os.makedirs(nltk_data_dir, exist_ok=True)

    # Try to download required packages
    packages = ["punkt", "punkt_tab", "stopwords"]
    for package in packages:
        try:
            # First check if package exists locally
            if package == "punkt":
                nltk.data.find("tokenizers/punkt")
            elif package == "punkt_tab":
                nltk.data.find("tokenizers/punkt_tab")
            elif package == "stopwords":
                nltk.data.find("corpora/stopwords")
            logger.debug(f"NLTK package '{package}' already available locally")
        except LookupError:
            # Package not found, try to download
            try:
                nltk.download(package, quiet=True, raise_on_error=True)
                logger.info(f"✅ Downloaded NLTK package: {package}")
            except Exception as e:
                logger.warning(f"⚠️  Failed to download NLTK package '{package}': {e}")
                logger.warning(
                    f"NLTK functionality requiring '{package}' may be limited"
                )


# Initialize NLTK data
try:
    download_nltk_data()
except Exception as e:
    logger.warning(
        f"NLTK initialization failed: {e}. Text processing features may be limited."
    )
    pass


# Safe NLTK wrappers that fallback when data is unavailable
def safe_sent_tokenize(text: str) -> List[str]:
    """Tokenize text into sentences with fallback"""
    try:
        return sent_tokenize(text)
    except LookupError:
        # Fallback to simple sentence splitting
        logger.debug("NLTK punkt not available, using simple sentence splitting")
        import re

        # Simple sentence splitter based on punctuation
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]


def safe_word_tokenize(text: str) -> List[str]:
    """Tokenize text into words with fallback"""
    try:
        return word_tokenize(text)
    except LookupError:
        # Fallback to simple word splitting
        logger.debug("NLTK punkt not available, using simple word splitting")
        import re

        words = re.findall(r"\b\w+\b", text.lower())
        return words


def safe_get_stopwords() -> set:
    """Get stopwords with fallback"""
    try:
        return set(stopwords.words("english"))
    except LookupError:
        # Fallback to basic stopwords list
        logger.debug("NLTK stopwords not available, using basic stopword list")
        return {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "should",
            "could",
            "may",
            "might",
            "must",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
        }


@dataclass
class ChunkMetadata:
    """Metadata for each chunk"""

    chunk_index: int
    start_char: int
    end_char: int
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    section_path: List[str] = field(default_factory=list)
    heading_level: Optional[int] = None
    is_table: bool = False
    is_list: bool = False
    semantic_type: str = "text"  # text, code, table, list, heading
    entities: List[Dict[str, str]] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


@dataclass
class ProcessedChunk:
    """Processed chunk with content and metadata"""

    content: str
    metadata: ChunkMetadata
    local_context: Optional[str] = None
    document_context: Optional[str] = None
    global_context: Optional[str] = None
    embedding: Optional[List[float]] = None


def chunk_to_row(chunk: Any) -> Dict[str, Any]:
    """Normalize a chunk to a uniform dict for DB/KG persistence.

    The pipeline carries chunks as ``ProcessedChunk`` dataclasses, but some
    synthetic/legacy chunks arrive as plain dicts. This collapses both into one
    shape (content, token_count, char/page spans, metadata dict, is_table) so
    consumers never have to guess whether to call ``.get()`` or attribute access.
    """
    if isinstance(chunk, dict):
        meta = chunk.get("metadata") or {}
        content = chunk.get("content", "")
        token_count = chunk.get("token_count") or meta.get("token_count")
        start_char = chunk.get("start_char", meta.get("start_char"))
        end_char = chunk.get("end_char", meta.get("end_char"))
        start_page = chunk.get("start_page", meta.get("start_page"))
        end_page = chunk.get("end_page", meta.get("end_page"))
        is_table = bool(chunk.get("is_table") or meta.get("is_table"))
    else:
        # ProcessedChunk (or anything with .content/.metadata)
        md = getattr(chunk, "metadata", None)
        meta = asdict(md) if is_dataclass(md) else (md or {})
        content = getattr(chunk, "content", "")
        token_count = meta.get("token_count")
        start_char = meta.get("start_char")
        end_char = meta.get("end_char")
        start_page = meta.get("start_page")
        end_page = meta.get("end_page")
        is_table = bool(meta.get("is_table"))

    return {
        "content": content,
        "token_count": token_count,
        "start_char": start_char,
        "end_char": end_char,
        "start_page": start_page,
        "end_page": end_page,
        # Surface these so DocumentChunk columns are populated (add_chunks reads
        # them at the top level), not just buried in the metadata JSON.
        "section_path": meta.get("section_path"),
        "heading_level": meta.get("heading_level"),
        "is_list": bool(meta.get("is_list")),
        "is_table": is_table,
        "metadata": meta,
    }


@dataclass
class DocumentStructure:
    """Document structure information"""

    title: str
    sections: List[Dict[str, Any]]
    hierarchy: Dict[str, List[str]]
    total_pages: int
    total_chunks: int
    document_type: str
    summary: Optional[str] = None
    key_topics: List[str] = field(default_factory=list)


class ModernDocumentProcessor:
    """Enhanced document processor with intelligent chunking and contextual understanding"""

    def __init__(self):
        # Initialize NLP models
        self.nlp = spacy.load("en_core_web_sm")
        self.tokenizer = tiktoken.get_encoding("cl100k_base")
        self.sentence_model = SentenceTransformer("all-MiniLM-L6-v2")

        # Chunking parameters
        self.target_chunk_size = 512  # tokens
        self.max_chunk_size = 1024
        self.min_chunk_size = 100
        self.chunk_overlap = 50  # tokens

        # Context window sizes
        self.local_context_window = 2  # chunks before/after
        self.document_context_samples = 5  # representative chunks
        self.global_context_docs = 3  # related documents

    async def process_document(
        self,
        file_path: str,
        content_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Process document with intelligent chunking and structure extraction"""
        try:
            logger.info(f"Processing document: {file_path}")

            # Extract raw content and structure
            raw_content, structure_info = await self._extract_content_and_structure(
                file_path, content_type
            )

            # Perform intelligent chunking
            chunks = await self._intelligent_chunking(raw_content, structure_info)

            # Extract document-level context
            document_structure = await self._analyze_document_structure(
                chunks, structure_info, metadata
            )

            # Generate summary
            document_structure.summary = await self._generate_document_summary(chunks)

            # Extract key topics
            document_structure.key_topics = await self._extract_key_topics(chunks)

            # Calculate file hash
            file_hash = await self._calculate_file_hash(file_path)

            return {
                "chunks": chunks,
                "structure": document_structure,
                "metadata": {
                    "file_path": file_path,
                    "content_type": content_type,
                    "file_hash": file_hash,
                    "processed_at": datetime.utcnow().isoformat(),
                    "processor_version": "2.0",
                    **metadata,
                }
                if metadata
                else {
                    "file_path": file_path,
                    "content_type": content_type,
                    "file_hash": file_hash,
                    "processed_at": datetime.utcnow().isoformat(),
                    "processor_version": "2.0",
                },
            }

        except Exception as e:
            logger.error(f"Document processing failed: {e}")
            raise

    async def _extract_content_and_structure(
        self, file_path: str, content_type: str
    ) -> Tuple[str, Dict[str, Any]]:
        """Extract content and structure based on file type"""

        if content_type == "application/pdf":
            return await self._extract_pdf_content(file_path)
        elif content_type in [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ]:
            return await self._extract_docx_content(file_path)
        elif content_type.startswith("text/"):
            return await self._extract_text_content(file_path)
        else:
            raise ValueError(f"Unsupported content type: {content_type}")

    async def _extract_pdf_content(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract content and structure from PDF"""
        content_parts = []
        structure_info = {"pages": [], "sections": [], "tables": [], "images": []}

        with open(file_path, "rb") as f:
            with PDF(f) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Extract text
                    text = page.extract_text() or ""
                    content_parts.append(text)

                    # Extract structure
                    structure_info["pages"].append(
                        {
                            "page_num": page_num + 1,
                            "text": text,
                            "tables": len(page.extract_tables()),
                            "bbox": page.bbox,
                        }
                    )

                    # Extract tables
                    tables = page.extract_tables()
                    for table_idx, table in enumerate(tables):
                        structure_info["tables"].append(
                            {"page": page_num + 1, "index": table_idx, "data": table}
                        )

        # Detect sections based on formatting
        full_content = "\n\n".join(content_parts)
        sections = self._detect_sections(full_content)
        structure_info["sections"] = sections

        return full_content, structure_info

    async def _extract_docx_content(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract content and structure from DOCX"""
        doc = docx.Document(file_path)
        content_parts = []
        structure_info = {"paragraphs": [], "sections": [], "tables": [], "styles": {}}

        current_section = []
        current_heading = None

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            style_name = para.style.name

            # Detect headings
            if "Heading" in style_name:
                if current_section:
                    structure_info["sections"].append(
                        {
                            "heading": current_heading,
                            "content": "\n".join(current_section),
                            "level": int(style_name[-1])
                            if style_name[-1].isdigit()
                            else 1,
                        }
                    )
                current_heading = text
                current_section = []
            else:
                current_section.append(text)

            content_parts.append(text)
            structure_info["paragraphs"].append({"text": text, "style": style_name})

        # Add last section
        if current_section:
            structure_info["sections"].append(
                {
                    "heading": current_heading,
                    "content": "\n".join(current_section),
                    "level": 1,
                }
            )

        # Extract tables
        for table_idx, table in enumerate(doc.tables):
            table_data = []
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells]
                table_data.append(row_data)
            structure_info["tables"].append({"index": table_idx, "data": table_data})

        return "\n\n".join(content_parts), structure_info

    async def _extract_text_content(self, file_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract content from plain text file with encoding detection"""
        import chardet

        # Read file in binary mode to detect encoding
        with open(file_path, "rb") as f:
            raw_data = f.read()

        # Detect encoding
        detected = chardet.detect(raw_data)
        encoding = detected.get("encoding", "utf-8")
        confidence = detected.get("confidence", 0)

        logger.info(f"Detected encoding: {encoding} (confidence: {confidence:.2f})")

        # Try detected encoding first, fall back to utf-8, then latin-1
        for enc in [encoding, "utf-8", "latin-1", "cp1252"]:
            try:
                content = raw_data.decode(enc)
                logger.info(f"Successfully decoded with {enc}")
                break
            except (UnicodeDecodeError, AttributeError, LookupError):
                continue
        else:
            # Last resort: decode with errors='ignore'
            content = raw_data.decode("utf-8", errors="ignore")
            logger.warning(f"Used UTF-8 with errors='ignore' for {file_path}")

        structure_info = {
            "sections": self._detect_sections(content),
            "paragraphs": content.split("\n\n"),
            "detected_encoding": encoding,
            "encoding_confidence": confidence,
        }

        return content, structure_info

    def _detect_sections(self, text: str) -> List[Dict[str, Any]]:
        """Detect sections in text based on patterns"""
        sections = []
        lines = text.split("\n")

        current_section = {
            "heading": "Introduction",
            "content": [],
            "level": 1,
            "start_line": 0,
        }

        # Common heading patterns
        heading_patterns = [
            (r"^#{1,6}\s+(.+)$", "markdown"),  # Markdown headings
            (r"^([A-Z][A-Z\s]+)$", "uppercase"),  # UPPERCASE HEADINGS
            (r"^(\d+\.?\s+.+)$", "numbered"),  # 1. Heading
            (r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*):?\s*$", "title_case"),  # Title Case
        ]

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            # Check if line is a heading
            is_heading = False
            for pattern, style in heading_patterns:
                import re

                match = re.match(pattern, stripped)
                if match:
                    # Save current section
                    if current_section["content"]:
                        sections.append(current_section)

                    # Start new section
                    level = stripped.count("#") if style == "markdown" else 1
                    heading_text = match.group(1).strip("#").strip()

                    current_section = {
                        "heading": heading_text,
                        "content": [],
                        "level": level,
                        "start_line": i,
                    }
                    is_heading = True
                    break

            if not is_heading:
                current_section["content"].append(line)

        # Add last section
        if current_section["content"]:
            sections.append(current_section)

        # Clean up sections
        for section in sections:
            section["content"] = "\n".join(section["content"]).strip()

        return sections

    async def _intelligent_chunking(
        self, content: str, structure_info: Dict[str, Any]
    ) -> List[ProcessedChunk]:
        """Perform intelligent chunking that preserves semantic boundaries"""
        chunks = []

        # Get sections
        sections = structure_info.get("sections", [])
        if not sections:
            # Fallback to paragraph-based chunking
            sections = [{"heading": "Document", "content": content, "level": 1}]

        chunk_index = 0

        for section in sections:
            section_content = section["content"]
            section_path = [section["heading"] or "Untitled"]

            # Skip empty sections
            if not section_content.strip():
                continue

            # Chunk the section
            section_chunks = await self._chunk_section(
                section_content, section_path, section.get("level", 1), chunk_index
            )

            chunks.extend(section_chunks)
            chunk_index += len(section_chunks)

        return chunks

    async def _chunk_section(
        self,
        content: str,
        section_path: List[str],
        heading_level: int,
        start_index: int,
    ) -> List[ProcessedChunk]:
        """Chunk a section intelligently"""
        chunks = []

        # Split into sentences using safe wrapper
        sentences = safe_sent_tokenize(content)

        current_chunk = []
        current_tokens = 0
        chunk_start_char = 0

        for sent_idx, sentence in enumerate(sentences):
            sent_tokens = len(self.tokenizer.encode(sentence))

            # Check if adding this sentence would exceed target size
            if current_tokens + sent_tokens > self.target_chunk_size and current_chunk:
                # Create chunk
                chunk_content = " ".join(current_chunk)

                # Detect semantic type
                semantic_type = self._detect_semantic_type(chunk_content)

                # Extract entities and keywords
                entities = self._extract_entities(chunk_content)
                keywords = self._extract_keywords(chunk_content)

                chunk = ProcessedChunk(
                    content=chunk_content,
                    metadata=ChunkMetadata(
                        chunk_index=start_index + len(chunks),
                        start_char=chunk_start_char,
                        end_char=chunk_start_char + len(chunk_content),
                        section_path=section_path,
                        heading_level=heading_level,
                        semantic_type=semantic_type,
                        entities=entities,
                        keywords=keywords,
                    ),
                )

                chunks.append(chunk)

                # Start new chunk with overlap
                overlap_sentences = self._get_overlap_sentences(
                    current_chunk, self.chunk_overlap
                )
                current_chunk = overlap_sentences + [sentence]
                current_tokens = sum(
                    len(self.tokenizer.encode(s)) for s in current_chunk
                )
                chunk_start_char += len(chunk_content) - len(
                    " ".join(overlap_sentences)
                )
            else:
                current_chunk.append(sentence)
                current_tokens += sent_tokens

        # Add final chunk
        if current_chunk:
            chunk_content = " ".join(current_chunk)

            chunk = ProcessedChunk(
                content=chunk_content,
                metadata=ChunkMetadata(
                    chunk_index=start_index + len(chunks),
                    start_char=chunk_start_char,
                    end_char=chunk_start_char + len(chunk_content),
                    section_path=section_path,
                    heading_level=heading_level,
                    semantic_type=self._detect_semantic_type(chunk_content),
                    entities=self._extract_entities(chunk_content),
                    keywords=self._extract_keywords(chunk_content),
                ),
            )

            chunks.append(chunk)

        return chunks

    def _get_overlap_sentences(
        self, sentences: List[str], target_tokens: int
    ) -> List[str]:
        """Get sentences for overlap"""
        overlap_sentences = []
        tokens = 0

        for sent in reversed(sentences):
            sent_tokens = len(self.tokenizer.encode(sent))
            if tokens + sent_tokens <= target_tokens:
                overlap_sentences.insert(0, sent)
                tokens += sent_tokens
            else:
                break

        return overlap_sentences

    def _detect_semantic_type(self, text: str) -> str:
        """Detect the semantic type of text"""
        # Simple heuristics - can be enhanced with ML
        if text.count("|") > 5 or text.count("\t") > 5:
            return "table"
        elif any(text.startswith(marker) for marker in ["•", "-", "*", "1.", "2."]):
            return "list"
        elif text.count("```") >= 2 or text.count("    ") > len(text.split("\n")) / 2:
            return "code"
        elif len(text.split()) < 10 and text.isupper():
            return "heading"
        else:
            return "text"

    def _extract_entities(self, text: str) -> List[Dict[str, str]]:
        """Extract named entities from text"""
        doc = self.nlp(text)
        entities = []

        for ent in doc.ents:
            entities.append(
                {
                    "text": ent.text,
                    "type": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char,
                }
            )

        return entities

    def _extract_keywords(self, text: str, max_keywords: int = 5) -> List[str]:
        """Extract keywords using TF-IDF"""
        try:
            # Tokenize and remove stopwords using safe wrappers
            stop_words = safe_get_stopwords()
            words = safe_word_tokenize(text.lower())
            words = [
                w for w in words if w.isalnum() and w not in stop_words and len(w) > 2
            ]

            if not words:
                return []

            # Simple frequency-based extraction
            from collections import Counter

            word_freq = Counter(words)

            # Get top keywords
            keywords = [word for word, _ in word_freq.most_common(max_keywords)]

            return keywords
        except Exception as e:
            logger.error(f"Keyword extraction failed: {e}")
            return []

    async def _analyze_document_structure(
        self,
        chunks: List[ProcessedChunk],
        structure_info: Dict[str, Any],
        metadata: Optional[Dict[str, Any]],
    ) -> DocumentStructure:
        """Analyze overall document structure"""

        # Build hierarchy
        hierarchy = {}
        for chunk in chunks:
            path = chunk.metadata.section_path
            if path:
                section = path[0]
                if section not in hierarchy:
                    hierarchy[section] = []
                hierarchy[section].append(chunk.metadata.chunk_index)

        # Get document type
        doc_type = "unknown"
        if metadata:
            doc_type = metadata.get("document_type", "unknown")
        elif "contract" in str(chunks).lower():
            doc_type = "contract"
        elif "report" in str(chunks).lower():
            doc_type = "report"

        return DocumentStructure(
            title=metadata.get("title", "Untitled") if metadata else "Untitled",
            sections=structure_info.get("sections", []),
            hierarchy=hierarchy,
            total_pages=len(structure_info.get("pages", [])),
            total_chunks=len(chunks),
            document_type=doc_type,
        )

    async def _generate_document_summary(self, chunks: List[ProcessedChunk]) -> str:
        """Generate document summary from chunks"""
        # Take first few and last few chunks
        sample_chunks = chunks[:3] + chunks[-2:] if len(chunks) > 5 else chunks

        # Combine content
        combined_text = " ".join([chunk.content for chunk in sample_chunks])

        # Simple extractive summary (can be replaced with abstractive)
        sentences = safe_sent_tokenize(combined_text)
        if len(sentences) > 5:
            # Use first 2 and last sentence
            summary = " ".join(sentences[:2] + [sentences[-1]])
        else:
            summary = combined_text

        # Limit length
        if len(summary.split()) > 100:
            words = summary.split()[:100]
            summary = " ".join(words) + "..."

        return summary

    async def _extract_key_topics(self, chunks: List[ProcessedChunk]) -> List[str]:
        """Extract key topics from document"""
        # Collect all keywords
        all_keywords = []
        for chunk in chunks:
            all_keywords.extend(chunk.metadata.keywords)

        # Count frequency
        from collections import Counter

        keyword_freq = Counter(all_keywords)

        # Get top topics
        topics = [topic for topic, _ in keyword_freq.most_common(10)]

        return topics

    async def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of file"""
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()


class ContextualEmbeddingGenerator:
    """Generate contextual embeddings with 3-level context"""

    def __init__(self):
        self.openai_client = llm_provider.failover_client()
        self.context_weights = {
            "local": 0.5,
            "document": 0.3,
            "global": 0.2,
        }

    async def generate_embeddings(
        self,
        chunks: List[ProcessedChunk],
        document_metadata: Dict[str, Any],
        use_voyage: bool = False,
    ) -> List[Dict[str, Any]]:
        """Generate TRUE 3-level contextual embeddings for chunks.

        Each chunk gets three genuinely distinct vectors:

        * **local** — the chunk + its neighbouring chunks and section path
        * **document** — the chunk + document title/sections/topics
        * **global** — the chunk + related documents actually found in the
          vector store (tenant-scoped), not a placeholder

        All texts for a document are embedded in batched API calls
        (2 calls for a typical document instead of one per chunk), and the
        per-level vectors are stored so the multi-collection weighted
        retrieval merge compares different representations — the thing the
        architecture always claimed.
        """
        if not chunks:
            return []

        document_context = await self._get_document_context(chunks, document_metadata)

        # Real global context: one tenant-scoped related-documents lookup per
        # document (keyed off the document context), shared across its chunks.
        related_summary = await self._find_related_documents(
            document_context, document_metadata
        )

        local_texts: List[str] = []
        doc_texts: List[str] = []
        global_texts: List[str] = []
        contexts: List[Dict[str, str]] = []

        for i, chunk in enumerate(chunks):
            local_context = await self._get_local_context(chunks, i)
            global_context = self._build_global_context(chunk, related_summary)

            snippet = chunk.content[:1000]
            local_texts.append(f"{chunk.content} {local_context}")
            doc_texts.append(f"{snippet} {document_context}")
            global_texts.append(f"{snippet} {global_context}")
            contexts.append(
                {
                    "local_context": local_context,
                    "document_context": document_context,
                    "global_context": global_context,
                }
            )

        # Batch-embed all three levels (local set first — it carries the
        # full chunk text and dominates retrieval quality).
        all_vectors = await self._embed_batch(local_texts + doc_texts + global_texts)
        n = len(chunks)
        local_vecs = all_vectors[:n]
        doc_vecs = all_vectors[n : 2 * n]
        global_vecs = all_vectors[2 * n : 3 * n]

        embeddings = []
        for i, chunk in enumerate(chunks):
            unified = [
                (lv + dv + gv) / 3.0
                for lv, dv, gv in zip(local_vecs[i], doc_vecs[i], global_vecs[i])
            ]
            embeddings.append(
                {
                    "chunk_id": f"{document_metadata.get('document_id', 'unknown')}_chunk_{i}",
                    "content": chunk.content,
                    "embedding": unified,
                    "embeddings": {
                        "local": local_vecs[i],
                        "document": doc_vecs[i],
                        "global": global_vecs[i],
                    },
                    "metadata": {
                        **chunk.metadata.__dict__,
                        **contexts[i],
                    },
                }
            )

        return embeddings

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts, batched, with OpenAI → Ollama failover.

        The whole call is retried against the fallback rather than individual
        batches: a document must not end up half in one vector space and half
        in another, since the two halves would then be mutually unsearchable.
        """
        provider = llm_provider.embedding_provider()
        try:
            return await self._embed_batch_with(texts, provider)
        except Exception as e:
            if provider.name != "openai" or not llm_provider.note_failure(e):
                raise
            fallback = llm_provider.embedding_provider()
            logger.warning(
                "Embedding batch of %d via Ollama (%s, %dd) after OpenAI failure: %s",
                len(texts),
                fallback.embed_model,
                fallback.embed_dims,
                e,
            )
            return await self._embed_batch_with(texts, fallback)

    async def _embed_batch_with(self, texts: List[str], provider) -> List[List[float]]:
        """Embed against one explicit provider, verifying vector width."""
        client = llm_provider.client_for(provider)
        vectors: List[List[float]] = []
        # Ollama serves embeddings from a single local process; large batches
        # queue up behind one another and blow the request timeout.
        batch_size = 16 if provider.is_local else 96
        for i in range(0, len(texts), batch_size):
            kwargs: Dict[str, Any] = {
                "input": [t[:8000] for t in texts[i : i + batch_size]],
                "model": provider.embed_model,
            }
            if provider.name == "openai":
                kwargs["dimensions"] = provider.embed_dims
            response = await client.embeddings.create(**kwargs)
            vectors.extend(d.embedding for d in response.data)

        if vectors and len(vectors[0]) != provider.embed_dims:
            raise ValueError(
                f"{provider.name} model '{provider.embed_model}' returned "
                f"{len(vectors[0])}-dim vectors but config declares "
                f"{provider.embed_dims}. Set the matching dimension value — "
                f"these vectors cannot be stored safely."
            )
        if provider.name == "openai":
            llm_provider.note_success()
        return vectors

    async def _find_related_documents(
        self, document_context: str, metadata: Dict[str, Any]
    ) -> str:
        """Find genuinely related documents in the vector store (best-effort).

        Tenant-scoped when an owner is known; excludes the document being
        indexed. Returns a short summary string, or "" when the store is
        empty/unavailable (first document, cold start).
        """
        try:
            from apps.api.services.document.vector_store import ModernVectorStore

            store = ModernVectorStore()
            probe = await self._embed_batch([document_context[:4000]])
            filters: Dict[str, Any] = {}
            if metadata.get("owner_id"):
                filters["owner_id"] = metadata["owner_id"]
            results = await store.search_with_context(
                query_embedding=probe[0],
                context_level="document",
                top_k=5,
                filters=filters or None,
            )
            current_doc = str(metadata.get("document_id", ""))
            related = []
            seen_docs = set()
            for r in results:
                doc_id = str(getattr(r, "document_id", ""))
                if not doc_id or doc_id == current_doc or doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                title = (
                    (getattr(r, "metadata", None) or {})
                    .get("document_structure", {})
                    .get("title")
                ) or f"document {doc_id[:8]}"
                excerpt = (getattr(r, "content", "") or "")[:120]
                related.append(f"{title}: {excerpt}")
                if len(related) >= 3:
                    break
            if not related:
                return ""
            return "[Related documents]: " + " | ".join(related)
        except Exception as e:
            logger.debug(f"Related-document lookup skipped: {e}")
            return ""

    @staticmethod
    def _build_global_context(chunk: ProcessedChunk, related_summary: str) -> str:
        """Cross-document context: real related docs + this chunk's topics."""
        parts = []
        if related_summary:
            parts.append(related_summary)
        if chunk.metadata.keywords:
            parts.append(f"[Related Topics]: {', '.join(chunk.metadata.keywords[:3])}")
        return (
            " ".join(parts)
            if parts
            else "[Global Context]: first document in this workspace"
        )

    async def _get_local_context(
        self, chunks: List[ProcessedChunk], chunk_index: int, window_size: int = 2
    ) -> str:
        """Get local context from surrounding chunks"""
        context_parts = []

        # Previous chunks
        for i in range(max(0, chunk_index - window_size), chunk_index):
            context_parts.append(
                f"[Previous {chunk_index - i}]: {chunks[i].content[:100]}..."
            )

        # Current chunk section info
        current_chunk = chunks[chunk_index]
        if current_chunk.metadata.section_path:
            context_parts.append(
                f"[Section]: {' > '.join(current_chunk.metadata.section_path)}"
            )

        # Next chunks
        for i in range(
            chunk_index + 1, min(len(chunks), chunk_index + window_size + 1)
        ):
            context_parts.append(
                f"[Next {i - chunk_index}]: {chunks[i].content[:100]}..."
            )

        return " ".join(context_parts)

    async def _get_document_context(
        self, chunks: List[ProcessedChunk], metadata: Dict[str, Any]
    ) -> str:
        """Get document-level context"""
        context_parts = []

        # Document metadata
        if metadata.get("title"):
            context_parts.append(f"[Document]: {metadata['title']}")

        if metadata.get("document_type"):
            context_parts.append(f"[Type]: {metadata['document_type']}")

        # Section overview
        sections = set()
        for chunk in chunks:
            if chunk.metadata.section_path:
                sections.add(chunk.metadata.section_path[0])

        if sections:
            context_parts.append(f"[Sections]: {', '.join(list(sections)[:5])}")

        # Key topics
        all_keywords = []
        for chunk in chunks:
            all_keywords.extend(chunk.metadata.keywords)

        from collections import Counter

        top_keywords = [kw for kw, _ in Counter(all_keywords).most_common(5)]
        if top_keywords:
            context_parts.append(f"[Topics]: {', '.join(top_keywords)}")

        return " ".join(context_parts)

    async def _get_global_context(
        self, chunk: ProcessedChunk, metadata: Dict[str, Any]
    ) -> str:
        """Get global context from related documents"""
        # In production, this would query the vector store for related documents
        # For now, return placeholder
        context_parts = []

        # Document collection info
        if metadata.get("collection"):
            context_parts.append(f"[Collection]: {metadata['collection']}")

        # Related topics (would come from knowledge graph)
        if chunk.metadata.keywords:
            context_parts.append(
                f"[Related Topics]: {', '.join(chunk.metadata.keywords[:3])}"
            )

        return (
            " ".join(context_parts)
            if context_parts
            else "[Global Context]: No related documents found"
        )

    async def _generate_contextual_embedding(
        self,
        content: str,
        local_context: str,
        document_context: str,
        global_context: str,
        use_voyage: bool = False,
    ) -> List[float]:
        """Generate one embedding in the active embedding space."""

        combined_text = f"{content} {local_context} {document_context} {global_context}"

        try:
            # Routed through _embed_batch so this shares the provider failover
            # and width verification rather than re-implementing them.
            vectors = await self._embed_batch([combined_text])
            return vectors[0]
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    async def generate_contextual_embedding(
        self,
        text: str,
        context_level: str = "local",
        conversation_history: Optional[List[Dict]] = None,
        document_context: Optional[List[str]] = None,
    ) -> List[float]:
        """Generate a single contextual embedding for queries"""

        context_parts = [text]

        if conversation_history:
            recent_messages = conversation_history[-3:]
            for msg in recent_messages:
                context_parts.append(f"[{msg['role']}]: {msg['content'][:100]}")

        if document_context:
            context_parts.append(f"[Documents]: {', '.join(document_context[:3])}")

        context_parts.append(f"[Level]: {context_level}")
        combined_text = " ".join(context_parts)

        # Query embeddings repeat constantly (nudge re-scans, common questions,
        # burst dispatches) — serve repeats from Redis instead of OpenAI.
        from apps.api.core.cache import get_cached_embedding, set_cached_embedding

        # Keyed by the *active* model: a query must be embedded by the same
        # model that produced the vectors it will be compared against, so
        # serving an OpenAI-cached query vector while running on Ollama would
        # search the Ollama space with an OpenAI vector and return nonsense.
        active_model = llm_provider.embedding_provider().embed_model
        cached = await get_cached_embedding(combined_text, active_model)
        if cached is not None:
            return cached

        try:
            vector = (await self._embed_batch([combined_text]))[0]
            await set_cached_embedding(
                combined_text,
                llm_provider.embedding_provider().embed_model,
                vector,
            )
            return vector
        except Exception as e:
            logger.error(f"Query embedding failed: {e}")
            raise
