#!/usr/bin/env python3
"""
Demo script for Voice Document Intelligence.

Uploads sample documents and runs example queries against the running API
to demonstrate the system's capabilities.

Usage:
    python scripts/demo.py [--base-url http://localhost:8000]
"""

import argparse
import sys
import textwrap
import time

import httpx

SAMPLE_DOCUMENTS = [
    {
        "filename": "architecture_overview.txt",
        "content": textwrap.dedent("""\
            # Architecture Overview

            ## Microservices Design
            The Voice Document Intelligence system follows a microservices architecture
            with the following core components:

            1. **API Gateway** - FastAPI-based REST API handling all client requests
            2. **Document Processor** - Intelligent chunking with semantic boundary detection
            3. **Embedding Service** - Multi-model embeddings (OpenAI, Voyage AI, local)
            4. **Vector Store** - Qdrant for similarity search across 4 collection levels
            5. **RAG Engine** - Context-aware retrieval augmented generation
            6. **Voice Pipeline** - Deepgram STT + Cartesia TTS + LiveKit WebRTC

            ## Data Flow
            Documents are uploaded, chunked with structure preservation, embedded at three
            context levels (local, document, global), and stored in Qdrant. Queries are
            enhanced, searched across multiple collections, and answered with source attribution.
        """),
    },
    {
        "filename": "security_protocols.txt",
        "content": textwrap.dedent("""\
            # Security Protocols

            ## Authentication
            All API endpoints require authentication via API key (X-API-Key header).
            Development mode allows bypassing authentication for local testing.

            ## Rate Limiting
            - Document upload: 5 requests per minute
            - Query endpoint: 30 requests per minute
            - Health check: 60 requests per minute

            ## Data Protection
            - Documents are stored with deduplication via content hashing
            - Soft delete preserves audit trail
            - PostgreSQL with async connection pooling
            - Redis for caching with automatic TTL expiry
        """),
    },
]

SAMPLE_QUERIES = [
    "What are the core components of the architecture?",
    "How does the document processing pipeline work?",
    "What security measures are in place?",
    "What rate limits are configured?",
]


def upload_document(client: httpx.Client, filename: str, content: str) -> dict:
    """Upload a document to the API."""
    files = {"file": (filename, content.encode(), "text/plain")}
    resp = client.post(
        "/api/v1/documents/upload", files=files, params={"use_enhanced": True}
    )
    resp.raise_for_status()
    return resp.json()


def query_documents(client: httpx.Client, query: str) -> dict:
    """Query the document corpus."""
    resp = client.post("/api/v1/query", json={"query": query, "use_enhanced": False})
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="Voice Document Intelligence Demo")
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="API base URL"
    )
    args = parser.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=60)

    # Health check
    print("Checking API health...")
    try:
        health = client.get("/health").json()
        print(f"  Status: {health['status']}  Version: {health['version']}\n")
    except Exception as e:
        print(f"  API not reachable: {e}")
        sys.exit(1)

    # Upload documents
    print("Uploading sample documents...")
    for doc in SAMPLE_DOCUMENTS:
        try:
            result = upload_document(client, doc["filename"], doc["content"])
            print(
                f"  {doc['filename']}: {result.get('status', 'ok')} (id: {result.get('document_id', 'n/a')[:8]}...)"
            )
        except httpx.HTTPStatusError as e:
            print(
                f"  {doc['filename']}: {e.response.status_code} - {e.response.text[:80]}"
            )

    # Wait for processing
    print("\nWaiting for documents to process...")
    time.sleep(5)

    # Run queries
    print("\nRunning sample queries:\n")
    for query in SAMPLE_QUERIES:
        print(f"  Q: {query}")
        try:
            start = time.perf_counter()
            result = query_documents(client, query)
            elapsed = (time.perf_counter() - start) * 1000

            answer = result.get("answer", "No answer")
            # Truncate long answers
            if len(answer) > 200:
                answer = answer[:200] + "..."
            print(f"  A: {answer}")
            print(f"  [{elapsed:.0f}ms, {len(result.get('sources', []))} sources]\n")
        except httpx.HTTPStatusError as e:
            print(f"  Error: {e.response.status_code}\n")

    print("Demo complete.")


if __name__ == "__main__":
    main()
