# Production Readiness Implementation Guide

This document tracks the implementation of critical fixes to make the system production-ready.

## ✅ Completed

### 1. Document Service Created
- **File**: `apps/api/services/document/document_service.py`
- **Status**: ✅ Complete
- **Description**: PostgreSQL-backed document service replacing in-memory storage
- **Features**:
  - Full CRUD operations for documents
  - Async database patterns
  - Proper error handling with custom exceptions
  - Document deduplication via file hash
  - Soft/hard delete support
  - Chunk management
  - Statistics aggregation

### 2. API Endpoints Updated to Use PostgreSQL
- **Status**: ✅ Complete
- **Files Modified**: `apps/api/main.py`
- **Endpoints Updated**:
  - ✅ POST `/api/v1/documents/upload` - Now creates documents in PostgreSQL with deduplication
  - ✅ POST `process_document_task` - Background task now updates database instead of in-memory dict
  - ✅ GET `/api/v1/documents` - Lists documents from database with pagination
  - ✅ GET `/api/v1/documents/{document_id}` - Gets document from database
  - ✅ DELETE `/api/v1/documents/{document_id}` - Soft deletes from database
- **Changes**:
  - Removed `documents_store: Dict[str, Dict] = {}` in-memory dictionary
  - All endpoints now use `document_service` with proper database sessions
  - Added proper UUID validation
  - Document chunks are now stored in database
  - Processing status tracked in database
  - Metadata stored in PostgreSQL JSON fields

## 🔄 In Progress

### 3. Next Priority - Fix Vector Dimension Mismatch
**Current Status**: Starting next

**Files to Update**:
- `apps/api/main.py`
  - Line 371: Replace `documents_store[document_id] = doc_record` with database call
  - Update all document endpoints to use `document_service`

**Changes Needed**:

```python
# BEFORE (line 371 in main.py):
documents_store[document_id] = doc_record

# AFTER:
from apps.api.services.document.document_service import document_service

async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_enhanced: bool = Query(True),
    session: AsyncSession = Depends(get_db)  # Add this
):
    # ... validation code ...

    # Create document in database
    document = await document_service.create_document(
        session=session,
        filename=file.filename,
        file_content=content,
        file_type=storage_result["content_type"],
        user_metadata={
            "use_enhanced": use_enhanced,
            "storage_type": storage_result["storage_type"],
            "file_path": storage_result["file_path"]
        }
    )

    # Update status to processing
    await document_service.update_document_status(
        session=session,
        document_id=document.id,
        status="processing"
    )
```

**Endpoints to Update**:
1. `POST /api/v1/documents/upload` (line 325)
2. `GET /api/v1/documents` (line 547)
3. `GET /api/v1/documents/{document_id}` (line 575)
4. `DELETE /api/v1/documents/{document_id}` (line 584)

## 📋 Pending Tasks

### 3. Fix Vector Dimension Mismatch
**Priority**: Critical
**Issue**: Qdrant expects 1536 dimensions, some embeddings are 3072
**Location**: `apps/api/services/embedding/`

**Solution**:
1. Standardize on OpenAI `text-embedding-3-small` (1536 dimensions)
2. Update Qdrant collection initialization
3. Add dimension validation before storing

### 4. Add Proper Error Handling
**Priority**: Critical
**Issue**: Bare `except Exception` blocks throughout codebase

**Files with Issues**:
```bash
# Find all bare exception handlers:
grep -r "except Exception:" apps/api/services/ | wc -l
# Result: 50+ instances
```

**Solution**:
1. Create custom exception hierarchy:
   ```python
   # apps/api/core/exceptions.py
   class BaseAPIException(Exception):
       """Base exception for all API errors"""
       pass

   class DocumentNotFoundError(BaseAPIException):
       """Document not found"""
       pass

   class EmbeddingError(BaseAPIException):
       """Embedding generation failed"""
       pass

   class VectorStoreError(BaseAPIException):
       """Vector store operation failed"""
       pass
   ```

2. Replace bare except blocks:
   ```python
   # BEFORE:
   try:
       result = await some_operation()
   except Exception as e:
       logger.error(f"Failed: {e}")
       return None

   # AFTER:
   try:
       result = await some_operation()
   except VectorStoreError as e:
       logger.error(f"Vector store operation failed: {e}")
       raise HTTPException(status_code=503, detail="Vector store unavailable")
   except Exception as e:
       logger.exception(f"Unexpected error in operation: {e}")
       raise HTTPException(status_code=500, detail="Internal server error")
   ```

### 5. Complete RAG Pipeline End-to-End
**Priority**: Critical
**Test Flow**: Upload → Chunk → Embed → Store → Query → Response

**Files Involved**:
- `apps/api/services/document/modern_processor.py` - Document chunking
- `apps/api/services/embedding/contextual_embedding.py` - Embedding generation
- `apps/api/services/document/vector_store.py` - Vector storage
- `apps/api/services/rag/llamaindex_service.py` - RAG queries

**Test Script**:
```python
# tests/test_rag_pipeline.py
async def test_complete_rag_pipeline():
    # 1. Upload document
    document = await document_service.create_document(...)

    # 2. Chunk document
    chunks = await doc_processor.process_document(...)

    # 3. Generate embeddings
    embeddings = await embedding_service.generate_embeddings(...)

    # 4. Store in vector DB
    await vector_store.store_embeddings(...)

    # 5. Query
    results = await rag_service.query(...)

    # 6. Verify response quality
    assert len(results) > 0
    assert results[0]['score'] > 0.7
```

### 6. Add Pydantic Models for Validation
**Priority**: High
**Status**: Partial - Document models exist, need more

**Models Needed**:
```python
# apps/api/models/requests.py
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    max_results: int = Field(default=10, ge=1, le=100)
    context_types: List[str] = Field(default=["local"])

class EmbeddingRequest(BaseModel):
    text: str = Field(..., min_length=1)
    model: str = Field(default="text-embedding-3-small")

# apps/api/models/responses.py
class QueryResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int
    processing_time_ms: float

class SearchResult(BaseModel):
    content: str
    score: float
    document_id: str
    chunk_id: str
    metadata: Dict[str, Any]
```

### 7. Implement Async Database Patterns
**Priority**: High
**Issue**: Some operations not using async, no connection pooling config

**Solution**:
```python
# apps/api/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,  # Add connection pooling
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=3600,
    poolclass=QueuePool
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)
```

### 8. Add Basic Tests
**Priority**: High
**Coverage Target**: >80% for core modules

**Test Structure**:
```
tests/
├── unit/
│   ├── test_document_service.py
│   ├── test_embedding_service.py
│   └── test_vector_store.py
├── integration/
│   ├── test_rag_pipeline.py
│   └── test_api_endpoints.py
└── conftest.py  # Fixtures
```

**Key Tests**:
1. Document CRUD operations
2. Embedding generation
3. Vector storage/retrieval
4. RAG query pipeline
5. API endpoint responses

### 9. Simple API Key Authentication
**Priority**: High
**Implementation**:

```python
# apps/api/core/auth.py
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required"
        )

    # Check against environment variable or database
    valid_keys = settings.api_keys.split(",")
    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )

    return api_key

# Usage in endpoints:
@app.post("/api/v1/documents/upload")
async def upload_document(
    api_key: str = Depends(verify_api_key),  # Add this
    file: UploadFile = File(...),
    ...
):
    ...
```

### 10. Comprehensive Health Checks
**Priority**: Medium
**Implementation**:

```python
# apps/api/routers/health.py
@router.get("/health/detailed")
async def health_check_detailed(session: AsyncSession = Depends(get_db)):
    health = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {}
    }

    # Check database
    try:
        await session.execute("SELECT 1")
        health["services"]["database"] = {"status": "healthy"}
    except Exception as e:
        health["services"]["database"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"

    # Check Redis
    try:
        redis = await get_redis_client()
        await redis.ping()
        health["services"]["redis"] = {"status": "healthy"}
    except Exception as e:
        health["services"]["redis"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"

    # Check Qdrant
    try:
        qdrant = get_qdrant_client()
        collections = await qdrant.get_collections()
        health["services"]["qdrant"] = {
            "status": "healthy",
            "collections": len(collections.collections)
        }
    except Exception as e:
        health["services"]["qdrant"] = {"status": "unhealthy", "error": str(e)}
        health["status"] = "degraded"

    return health
```

### 11. Code Cleanup
**Priority**: Medium

**Tasks**:
1. Remove dead code:
   ```bash
   # Find unused imports
   autoflake --remove-all-unused-imports --recursive apps/api/
   ```

2. Add type hints:
   ```bash
   # Check type coverage
   mypy apps/api/ --strict
   ```

3. Format code:
   ```bash
   black apps/api/
   ruff check apps/api/ --fix
   ```

### 12. Update Documentation
**Priority**: Medium

**Updates Needed**:
1. Add architecture diagram to README
2. Document API endpoints (OpenAPI/Swagger)
3. Add deployment guide
4. Create troubleshooting guide

## Implementation Order

### Phase 1: Core Functionality (Week 1)
1. ✅ Create document service
2. Update API endpoints to use document service
3. Fix vector dimension mismatch
4. Add proper error handling

### Phase 2: Validation & Testing (Week 2)
5. Complete RAG pipeline end-to-end
6. Add Pydantic models
7. Implement async database patterns
8. Add basic tests

### Phase 3: Security & Monitoring (Week 3)
9. Simple API key authentication
10. Comprehensive health checks

### Phase 4: Polish (Week 4)
11. Code cleanup
12. Update documentation

## Quick Commands

### Run Tests
```bash
pytest tests/ -v --cov=apps/api --cov-report=html
```

### Check Code Quality
```bash
ruff check apps/api/
mypy apps/api/ --strict
black --check apps/api/
```

### Database Migrations
```bash
alembic revision --autogenerate -m "Add document tables"
alembic upgrade head
```

### Start All Services
```bash
docker-compose up -d
```

## Success Metrics

- ✅ No in-memory data storage
- ✅ All database operations async
- ✅ Vector dimensions standardized
- ✅ Test coverage >80%
- ✅ No bare exception handlers
- ✅ API key authentication working
- ✅ Health checks return accurate status
- ✅ RAG pipeline working end-to-end
