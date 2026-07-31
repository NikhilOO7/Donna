"""
Regression tests for chunk_to_row — the normalizer that broke document processing.

The document pipeline carries chunks as ProcessedChunk dataclasses, but the
persistence loop used to call chunk.get(...) on them → AttributeError, which left
every uploaded document stuck/failed. chunk_to_row must accept both ProcessedChunk
objects and legacy dicts and return the persistence shape add_chunks expects.
"""

from apps.api.services.document.contextual_processor import (
    ChunkMetadata,
    ProcessedChunk,
    chunk_to_row,
)

# Keys document_service.add_chunks reads at the top level.
EXPECTED_KEYS = {
    "content",
    "token_count",
    "start_char",
    "end_char",
    "start_page",
    "end_page",
    "section_path",
    "heading_level",
    "is_list",
    "is_table",
    "metadata",
}


class TestChunkToRow:
    def test_processed_chunk_does_not_raise_and_reads_attributes(self):
        """The exact bug: a ProcessedChunk must normalize without .get() errors."""
        chunk = ProcessedChunk(
            content="Nikhil led the migration.",
            metadata=ChunkMetadata(
                chunk_index=3,
                start_char=10,
                end_char=35,
                start_page=1,
                end_page=1,
                section_path=["Experience", "Progcap"],
                heading_level=2,
                is_table=False,
                semantic_type="text",
            ),
        )
        row = chunk_to_row(chunk)
        assert row["content"] == "Nikhil led the migration."
        assert row["start_char"] == 10
        assert row["end_char"] == 35
        assert row["start_page"] == 1
        assert row["section_path"] == ["Experience", "Progcap"]
        assert row["heading_level"] == 2
        assert row["is_table"] is False
        assert row["metadata"]["semantic_type"] == "text"

    def test_synthetic_table_chunk_flagged(self):
        """Table chunks (e.g. from enrich_chunks) keep is_table for reranking."""
        chunk = ProcessedChunk(
            content="[TABLE]\n| a | b |",
            metadata=ChunkMetadata(
                chunk_index=9,
                start_char=0,
                end_char=16,
                is_table=True,
                semantic_type="table",
            ),
        )
        row = chunk_to_row(chunk)
        assert row["is_table"] is True
        assert row["metadata"]["semantic_type"] == "table"

    def test_legacy_dict_chunk_still_works(self):
        """Backward compatibility: a plain dict chunk normalizes the same way."""
        row = chunk_to_row(
            {
                "content": "legacy",
                "token_count": 12,
                "start_page": 2,
                "metadata": {"is_table": True, "section_path": ["S"]},
                "is_table": True,
            }
        )
        assert row["content"] == "legacy"
        assert row["token_count"] == 12
        assert row["start_page"] == 2
        assert row["is_table"] is True
        assert row["section_path"] == ["S"]

    def test_returns_exact_persistence_shape(self):
        """Every key add_chunks reads must be present for both input types."""
        pc = chunk_to_row(ProcessedChunk(content="x", metadata=ChunkMetadata(0, 0, 1)))
        dc = chunk_to_row({"content": "x", "metadata": {}})
        assert EXPECTED_KEYS <= set(pc)
        assert EXPECTED_KEYS <= set(dc)
