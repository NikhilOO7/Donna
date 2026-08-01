# apps/api/core/config.py
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Application
    app_name: str = "Donna"
    app_tagline: str = "She already knew."
    app_version: str = "0.2.0"
    environment: str = Field(
        default="development", validation_alias=AliasChoices("APP_ENV", "environment")
    )
    debug: bool = Field(
        default=False, validation_alias=AliasChoices("APP_DEBUG", "debug")
    )
    # SQL statement echo — independent of debug so debug mode doesn't flood
    # the console with every query. Opt in explicitly via DB_ECHO=true.
    db_echo: bool = Field(
        default=False, validation_alias=AliasChoices("DB_ECHO", "db_echo")
    )
    log_level: str = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "log_level")
    )
    log_format: str = Field(
        default="json", validation_alias=AliasChoices("LOG_FORMAT", "log_format")
    )  # "json" for prod, "console" for dev

    # API Settings
    api_prefix: str = "/api/v1"
    api_port: int = Field(
        default=8000, validation_alias=AliasChoices("API_PORT", "api_port")
    )
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:4321",
            "http://localhost:3000",
            "http://localhost:8000",
        ],
        validation_alias=AliasChoices("CORS_ORIGINS", "cors_origins"),
    )

    # Database Configuration - Updated for our setup
    postgres_user: str = Field(
        default="voicedoc",
        validation_alias=AliasChoices("POSTGRES_USER", "postgres_user"),
    )
    postgres_password: str = Field(
        default="voicedoc123",
        validation_alias=AliasChoices("POSTGRES_PASSWORD", "postgres_password"),
    )
    postgres_db: str = Field(
        default="voice_doc_intel",
        validation_alias=AliasChoices("POSTGRES_DB", "postgres_db"),
    )
    postgres_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("POSTGRES_HOST", "postgres_host"),
    )
    postgres_port: int = Field(
        default=5432, validation_alias=AliasChoices("POSTGRES_PORT", "postgres_port")
    )
    # Schema is owned by Alembic. In production, run `alembic upgrade head`
    # as a pre-deploy job. Set this true for local/dev convenience to run
    # migrations automatically on app startup.
    run_migrations_on_startup: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "RUN_MIGRATIONS_ON_STARTUP", "run_migrations_on_startup"
        ),
    )

    # Database URLs
    @property
    def postgres_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def database_url(self) -> str:
        return self.postgres_url

    # Redis Configuration
    redis_host: str = Field(
        default="localhost", validation_alias=AliasChoices("REDIS_HOST", "redis_host")
    )
    redis_port: int = Field(
        default=6379, validation_alias=AliasChoices("REDIS_PORT", "redis_port")
    )
    redis_password: str = Field(
        default="voicedoc123",
        validation_alias=AliasChoices("REDIS_PASSWORD", "redis_password"),
    )
    redis_db: int = Field(
        default=0, validation_alias=AliasChoices("REDIS_DB", "redis_db")
    )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # Vector Databases
    qdrant_host: str = Field(
        default="localhost", validation_alias=AliasChoices("QDRANT_HOST", "qdrant_host")
    )
    qdrant_port: int = Field(
        default=6333, validation_alias=AliasChoices("QDRANT_PORT", "qdrant_port")
    )
    qdrant_grpc_port: int = Field(
        default=6334,
        validation_alias=AliasChoices("QDRANT_GRPC_PORT", "qdrant_grpc_port"),
    )
    qdrant_collection_name: str = Field(
        default="voice_doc_embeddings",
        validation_alias=AliasChoices(
            "QDRANT_COLLECTION_NAME", "qdrant_collection_name"
        ),
    )

    # TigerGraph (Optional)
    tigergraph_host: str = Field(
        default="localhost",
        validation_alias=AliasChoices("TIGERGRAPH_HOST", "tigergraph_host"),
    )
    tigergraph_rest_port: int = Field(
        default=9000,
        validation_alias=AliasChoices("TIGERGRAPH_REST_PORT", "tigergraph_rest_port"),
    )
    tigergraph_gs_port: int = Field(
        default=14240,
        validation_alias=AliasChoices("TIGERGRAPH_GS_PORT", "tigergraph_gs_port"),
    )
    tigergraph_username: str = Field(
        default="tigergraph",
        validation_alias=AliasChoices("TIGERGRAPH_USERNAME", "tigergraph_username"),
    )
    tigergraph_password: str = Field(
        default="tigergraph123",
        validation_alias=AliasChoices("TIGERGRAPH_PASSWORD", "tigergraph_password"),
    )

    # AI/LLM Settings
    openai_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key")
    )
    frontend_url: str = Field(
        default="http://localhost:3000",
        validation_alias=AliasChoices("FRONTEND_URL", "frontend_url"),
    )

    openai_model: str = Field(
        default="gpt-4o", validation_alias=AliasChoices("OPENAI_MODEL", "openai_model")
    )
    # Tiered model policy — route each task to the cheapest capable tier:
    #   fast   → extraction, matching, classification, query rewriting
    #   smart  → synthesis (summaries, research briefs, RAG answers)
    #   vision → chart/figure understanding during document ingestion
    model_fast: str = Field(
        default="gpt-4o-mini", validation_alias=AliasChoices("MODEL_FAST", "model_fast")
    )
    model_smart: str = Field(
        default="gpt-4o", validation_alias=AliasChoices("MODEL_SMART", "model_smart")
    )
    model_vision: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("MODEL_VISION", "model_vision"),
    )
    chat_model: str = Field(
        default="gpt-4", validation_alias=AliasChoices("CHAT_MODEL", "chat_model")
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
    )
    embedding_dimensions: int = Field(
        default=1536,
        validation_alias=AliasChoices("EMBEDDING_DIMENSIONS", "embedding_dimensions"),
    )

    # Deepgram Settings
    deepgram_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("DEEPGRAM_API_KEY", "deepgram_api_key"),
    )
    deepgram_model: str = Field(
        default="nova-2-meeting",
        validation_alias=AliasChoices("DEEPGRAM_MODEL", "deepgram_model"),
    )
    deepgram_language: str = Field(
        default="en-US",
        validation_alias=AliasChoices("DEEPGRAM_LANGUAGE", "deepgram_language"),
    )
    deepgram_tier: str = Field(
        default="enhanced",
        validation_alias=AliasChoices("DEEPGRAM_TIER", "deepgram_tier"),
    )

    # Cartesia Settings
    cartesia_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("CARTESIA_API_KEY", "cartesia_api_key"),
    )
    cartesia_voice_id: str = Field(
        default="248be419-c632-4f23-adf1-5324ed7dbf1d",
        validation_alias=AliasChoices("CARTESIA_VOICE_ID", "cartesia_voice_id"),
    )
    cartesia_model: str = Field(
        default="sonic-turbo",
        validation_alias=AliasChoices("CARTESIA_MODEL", "cartesia_model"),
    )

    # Voice Processing Settings
    livekit_url: str = Field(
        default="ws://localhost:7880",
        validation_alias=AliasChoices("LIVEKIT_URL", "livekit_url"),
    )
    # URL BROWSERS use to reach LiveKit. Inside compose, livekit_url is the
    # docker-network hostname (ws://livekit:7880) which a browser can't
    # resolve — token endpoints must hand out this one instead.
    livekit_public_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("LIVEKIT_PUBLIC_URL", "livekit_public_url"),
    )

    @property
    def livekit_client_url(self) -> str:
        return self.livekit_public_url or self.livekit_url
    livekit_api_key: str = Field(
        default="", validation_alias=AliasChoices("LIVEKIT_API_KEY", "livekit_api_key")
    )
    livekit_api_secret: str = Field(
        default="",
        validation_alias=AliasChoices("LIVEKIT_API_SECRET", "livekit_api_secret"),
    )

    # Voice Pipeline Settings
    vad_threshold: float = Field(
        default=0.5, validation_alias=AliasChoices("VAD_THRESHOLD", "vad_threshold")
    )
    vad_min_speech_duration: float = Field(
        default=0.1,
        validation_alias=AliasChoices(
            "VAD_MIN_SPEECH_DURATION", "vad_min_speech_duration"
        ),
    )
    vad_min_silence_duration: float = Field(
        default=0.3,
        validation_alias=AliasChoices(
            "VAD_MIN_SILENCE_DURATION", "vad_min_silence_duration"
        ),
    )

    # Performance Settings
    audio_chunk_size_ms: int = Field(
        default=20,
        validation_alias=AliasChoices("AUDIO_CHUNK_SIZE_MS", "audio_chunk_size_ms"),
    )
    audio_buffer_size_ms: int = Field(
        default=100,
        validation_alias=AliasChoices("AUDIO_BUFFER_SIZE_MS", "audio_buffer_size_ms"),
    )
    max_concurrent_sessions: int = Field(
        default=100,
        validation_alias=AliasChoices(
            "MAX_CONCURRENT_SESSIONS", "max_concurrent_sessions"
        ),
    )
    enable_metrics: bool = Field(
        default=True, validation_alias=AliasChoices("ENABLE_METRICS", "enable_metrics")
    )

    # Storage Configuration (NEW - Local Storage Option)
    storage_type: str = Field(
        default="local", validation_alias=AliasChoices("STORAGE_TYPE", "storage_type")
    )  # "local" or "minio"
    local_storage_path: str = Field(
        default="./data/uploads",
        validation_alias=AliasChoices("LOCAL_STORAGE_PATH", "local_storage_path"),
    )
    allowed_file_types: List[str] = Field(
        default=[".pdf", ".docx", ".txt", ".doc"],
        validation_alias=AliasChoices("ALLOWED_FILE_TYPES", "allowed_file_types"),
    )

    # MinIO Storage (Kept for compatibility)
    minio_endpoint: str = Field(
        default="localhost:9000",
        validation_alias=AliasChoices("MINIO_ENDPOINT", "minio_endpoint"),
    )
    minio_access_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("MINIO_ACCESS_KEY", "minio_access_key"),
    )
    minio_secret_key: str = Field(
        default="minioadmin",
        validation_alias=AliasChoices("MINIO_SECRET_KEY", "minio_secret_key"),
    )
    minio_bucket: str = Field(
        default="documents",
        validation_alias=AliasChoices("MINIO_BUCKET", "minio_bucket"),
    )
    minio_bucket_name: str = Field(
        default="documents",
        validation_alias=AliasChoices("MINIO_BUCKET_NAME", "minio_bucket_name"),
    )
    minio_secure: bool = Field(
        default=False, validation_alias=AliasChoices("MINIO_SECURE", "minio_secure")
    )

    # Document Processing Settings
    chunk_size: int = Field(
        default=1000, validation_alias=AliasChoices("CHUNK_SIZE", "chunk_size")
    )
    chunk_overlap: int = Field(
        default=200, validation_alias=AliasChoices("CHUNK_OVERLAP", "chunk_overlap")
    )
    max_file_size: int = Field(
        default=100 * 1024 * 1024,
        validation_alias=AliasChoices("MAX_FILE_SIZE", "max_file_size"),
    )  # 100MB

    # Voyage AI (Better embeddings)
    voyage_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("VOYAGE_API_KEY", "voyage_api_key")
    )
    voyage_model: str = Field(
        default="voyage-3-large",
        validation_alias=AliasChoices("VOYAGE_MODEL", "voyage_model"),
    )

    # Exa (Web search for pre-meeting research)
    exa_api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("EXA_API_KEY", "exa_api_key")
    )

    # Postmark (Email delivery for post-meeting summaries)
    postmark_api_key: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("POSTMARK_API_KEY", "postmark_api_key"),
    )
    postmark_from_email: str = Field(
        default="meetings@example.com",
        validation_alias=AliasChoices("POSTMARK_FROM_EMAIL", "postmark_from_email"),
    )
    # Shared secret for the inbound-email webhook (H4): Postmark is configured
    # to POST to /api/v1/integrations/email/inbound?token=<this>.
    postmark_inbound_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "POSTMARK_INBOUND_TOKEN", "postmark_inbound_token"
        ),
    )

    # Google Calendar ingestion (H5) — optional OAuth app credentials.
    # Feature endpoints return 503 until these are set.
    google_client_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CLIENT_ID", "google_client_id"),
    )
    google_client_secret: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_CLIENT_SECRET", "google_client_secret"),
    )
    google_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/integrations/google/callback",
        validation_alias=AliasChoices("GOOGLE_REDIRECT_URI", "google_redirect_uri"),
    )

    # Neo4j (Knowledge Graph)
    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        validation_alias=AliasChoices("NEO4J_URI", "neo4j_uri"),
    )
    neo4j_user: str = Field(
        default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "neo4j_user")
    )
    neo4j_password: str = Field(
        default="voicedoc123",
        validation_alias=AliasChoices("NEO4J_PASSWORD", "neo4j_password"),
    )
    neo4j_database: str = Field(
        default="neo4j",
        validation_alias=AliasChoices("NEO4J_DATABASE", "neo4j_database"),
    )
    neo4j_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("NEO4J_ENABLED", "neo4j_enabled")
    )

    # Authentication
    api_key: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("API_KEY", "api_key")
    )
    require_api_key: bool = Field(
        default=False,
        validation_alias=AliasChoices("REQUIRE_API_KEY", "require_api_key"),
    )

    # JWT (user authentication)
    jwt_secret: str = Field(
        default="dev-secret-change-in-production",
        validation_alias=AliasChoices("JWT_SECRET", "jwt_secret"),
    )
    jwt_algorithm: str = Field(
        default="HS256", validation_alias=AliasChoices("JWT_ALGORITHM", "jwt_algorithm")
    )
    jwt_expiry_minutes: int = Field(
        default=1440,
        validation_alias=AliasChoices("JWT_EXPIRY_MINUTES", "jwt_expiry_minutes"),
    )
    # When true, meeting endpoints require a logged-in user (multi-tenant).
    # When false (dev/demo), auth is optional and meetings aren't owner-scoped.
    require_auth: bool = Field(
        default=False, validation_alias=AliasChoices("REQUIRE_AUTH", "require_auth")
    )

    # Durable job queue (Arq). When true, background work (agent dispatch,
    # research, summary) is enqueued to a durable Redis-backed queue and run
    # by the job worker (apps/workers/job_worker.py) with retries. When false
    # (dev/demo), work runs in-process via FastAPI BackgroundTasks.
    use_job_queue: bool = Field(
        default=False, validation_alias=AliasChoices("USE_JOB_QUEUE", "use_job_queue")
    )

    # Observability
    enable_tracing: bool = Field(
        default=False, validation_alias=AliasChoices("ENABLE_TRACING", "enable_tracing")
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        validation_alias=AliasChoices("OTLP_ENDPOINT", "otlp_endpoint"),
    )

    # Resilience
    allow_local_embedding_fallback: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "ALLOW_LOCAL_EMBEDDING_FALLBACK", "allow_local_embedding_fallback"
        ),
    )

    # Rate limiting
    rate_limit_upload: str = Field(
        default="5/minute",
        validation_alias=AliasChoices("RATE_LIMIT_UPLOAD", "rate_limit_upload"),
    )
    rate_limit_query: str = Field(
        default="30/minute",
        validation_alias=AliasChoices("RATE_LIMIT_QUERY", "rate_limit_query"),
    )
    # Global default applied to every endpoint (health/metrics exempted). The
    # per-endpoint limits above stack on top for the expensive routes.
    rate_limit_default: str = Field(
        default="200/minute",
        validation_alias=AliasChoices("RATE_LIMIT_DEFAULT", "rate_limit_default"),
    )

    # Latency Targets
    target_stt_latency_ms: int = Field(
        default=100,
        validation_alias=AliasChoices("TARGET_STT_LATENCY_MS", "target_stt_latency_ms"),
    )
    target_tts_latency_ms: int = Field(
        default=80,
        validation_alias=AliasChoices("TARGET_TTS_LATENCY_MS", "target_tts_latency_ms"),
    )
    target_llm_latency_ms: int = Field(
        default=1000,
        validation_alias=AliasChoices("TARGET_LLM_LATENCY_MS", "target_llm_latency_ms"),
    )
    target_total_latency_ms: int = Field(
        default=200,
        validation_alias=AliasChoices(
            "TARGET_TOTAL_LATENCY_MS", "target_total_latency_ms"
        ),
    )

    @field_validator("deepgram_api_key", "cartesia_api_key", mode="before")
    @classmethod
    def validate_required_keys(cls, v):
        # Make API keys optional for development
        # In production, you would uncomment the check below
        # if not v:
        #     raise ValueError(f"API key is required for enhanced voice processing")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def voice_pipeline_config(self) -> Dict[str, Any]:
        """Get voice pipeline configuration"""
        return {
            "vad": {
                "provider": "silero",
                "threshold": self.vad_threshold,
                "min_speech_duration": self.vad_min_speech_duration,
                "min_silence_duration": self.vad_min_silence_duration,
            },
            "stt": {
                "provider": "deepgram",
                "model": self.deepgram_model,
                "language": self.deepgram_language,
                "tier": self.deepgram_tier,
            },
            "tts": {
                "provider": "cartesia",
                "model": self.cartesia_model,
                "voice_id": self.cartesia_voice_id,
            },
            "performance": {
                "audio_chunk_size_ms": self.audio_chunk_size_ms,
                "audio_buffer_size_ms": self.audio_buffer_size_ms,
                "max_concurrent_sessions": self.max_concurrent_sessions,
                "targets": {
                    "stt_ms": self.target_stt_latency_ms,
                    "tts_ms": self.target_tts_latency_ms,
                    "total_ms": self.target_total_latency_ms,
                },
            },
        }

    # Local Storage Helper Methods (NEW)
    def get_storage_path(self, document_id: str, filename: str) -> Path:
        """Get the full path for storing a document"""
        base_path = Path(self.local_storage_path)
        doc_path = base_path / document_id
        doc_path.mkdir(parents=True, exist_ok=True)
        return doc_path / filename

    def get_upload_path(self) -> Path:
        """Get the upload directory path"""
        path = Path(self.local_storage_path)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
