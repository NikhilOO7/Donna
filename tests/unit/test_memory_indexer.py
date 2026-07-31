"""Unit tests for meeting-memory records and citation building."""

from apps.api.services.meeting.memory_indexer import build_memory_records
from apps.api.services.rag.rag_service import build_citation


def test_build_records_covers_summary_decisions_transcript_and_facts():
    records = build_memory_records(
        meeting_id="m1",
        meeting_title="Q2 Vendor Review",
        meeting_date="2026-07-31",
        summary_text="We compared vendors and chose Beacon.",
        decisions=[
            {
                "decision_text": "Go with Beacon Cloud",
                "owner": "Alice",
                "deadline": "2026-08-15",
                "context": 'Alice: "Let\'s go with Beacon."',
            }
        ],
        utterances=[
            {"speaker": "Alice", "text": "Beacon came in under budget."},
            {"speaker": "Bob", "text": "Agreed, their SLA is stronger too."},
        ],
        facts=[
            {
                "fact": "Beacon's quote is 12% under budget",
                "quote": "Beacon came in under budget.",
                "speaker": "Alice",
            }
        ],
    )

    kinds = [r["metadata"]["memory_kind"] for r in records]
    assert "summary" in kinds
    assert "decision" in kinds
    assert "transcript" in kinds
    assert "fact" in kinds

    # Every record carries the citation fields
    for r in records:
        assert r["metadata"]["source_type"] == "meeting_memory"
        assert r["metadata"]["meeting_title"] == "Q2 Vendor Review"
        assert r["metadata"]["meeting_date"] == "2026-07-31"

    decision = next(r for r in records if r["metadata"]["memory_kind"] == "decision")
    assert "Go with Beacon Cloud" in decision["content"]
    assert decision["metadata"]["quote"] == 'Alice: "Let\'s go with Beacon."'

    fact = next(r for r in records if r["metadata"]["memory_kind"] == "fact")
    assert fact["metadata"]["speaker"] == "Alice"


def test_failed_summary_is_not_memorized():
    records = build_memory_records(
        meeting_id="m1",
        meeting_title="X",
        meeting_date=None,
        summary_text="Summary generation failed: boom",
        decisions=[],
        utterances=[],
    )
    assert records == []


def test_citation_for_meeting_memory():
    citation = build_citation(
        {
            "source_type": "meeting_memory",
            "meeting_title": "Q2 Vendor Review",
            "meeting_date": "2026-07-31",
            "quote": "Beacon came in under budget.",
        }
    )
    assert citation["source_type"] == "meeting_memory"
    assert citation["citation"] == "Meeting: Q2 Vendor Review (2026-07-31)"
    assert citation["quote"] == "Beacon came in under budget."


def test_citation_for_document_with_page_and_section():
    citation = build_citation(
        {
            "document_structure": {"title": "Annual Report.pdf"},
            "section_path": ["Financials"],
            "page_number": 12,
        }
    )
    assert citation["source_type"] == "document"
    assert citation["citation"] == "Annual Report.pdf · Financials · p. 12"


def test_citation_handles_empty_metadata():
    citation = build_citation({})
    assert citation["source_type"] == "document"
    assert citation["citation"] is None
