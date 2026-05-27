# apps/api/core/config.py
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Application
    app_name: str = "Voice Document Intelligence"
    app_version: str = "0.2.0"
    environment: str = Field(default="development", env="APP_ENV")
    debug: bool = Field(default=False, env="APP_DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(
        default="json", env="LOG_FORMAT"
    )  # "json" for prod, "console" for dev

    # API Settings
    api_prefix: str = "/api/v1"
    api_port: int = Field(default=8000, env="API_PORT")
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:4321",
            "http://localhost:3000",
            "http://localhost:8000",
        ],
        env="CORS_ORIGINS",
    )

    # Database Configuration - Updated for our setup
    postgres_user: str = Field(default="voicedoc", env="POSTGRES_USER")
    postgres_password: str = Field(default="voicedoc123", env="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="voice_doc_intel", env="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", env="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, env="POSTGRES_PORT")
    # Schema is owned by Alembic. In production, run `alembic upgrade head`
    # as a pre-deploy job. Set this true for local/dev convenience to run
    # migrations automatically on app startup.
    run_migrations_on_startup: bool = Field(
        default=False, env="RUN_MIGRATIONS_ON_STARTUP"
    )

    # Database URLs
    @property
    def postgres_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def database_url(self) -> str:
        return self.postgres_url

    # Redis Configuration
    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_password: str = Field(default="voicedoc123", env="REDIS_PASSWORD")
    redis_db: int = Field(default=0, env="REDIS_DB")

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # Vector Databases
    qdrant_host: str = Field(default="localhost", env="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, env="QDRANT_PORT")
    qdrant_grpc_port: int = Field(default=6334, env="QDRANT_GRPC_PORT")
    qdrant_collection_name: str = Field(
        default="voice_doc_embeddings", env="QDRANT_COLLECTION_NAME"
    )

    # TigerGraph (Optional)
    tigergraph_host: str = Field(default="localhost", env="TIGERGRAPH_HOST")
    tigergraph_rest_port: int = Field(default=9000, env="TIGERGRAPH_REST_PORT")
    tigergraph_gs_port: int = Field(default=14240, env="TIGERGRAPH_GS_PORT")
    tigergraph_username: str = Field(default="tigergraph", env="TIGERGRAPH_USERNAME")
    tigergraph_password: str = Field(default="tigergraph123", env="TIGERGRAPH_PASSWORD")

    # AI/LLM Settings
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4-turbo", env="OPENAI_MODEL")
    chat_model: str = Field(default="gpt-4", env="CHAT_MODEL")
    embedding_model: str = Field(
        default="text-embedding-3-small", env="EMBEDDING_MODEL"
    )
    embedding_dimensions: int = Field(default=1536, env="EMBEDDING_DIMENSIONS")

    # Deepgram Settings
    deepgram_api_key: Optional[str] = Field(default=None, env="DEEPGRAM_API_KEY")
    deepgram_model: str = Field(default="nova-2-meeting", env="DEEPGRAM_MODEL")
    deepgram_language: str = Field(default="en-US", env="DEEPGRAM_LANGUAGE")
    deepgram_tier: str = Field(default="enhanced", env="DEEPGRAM_TIER")

    # Cartesia Settings
    cartesia_api_key: Optional[str] = Field(default=None, env="CARTESIA_API_KEY")
    cartesia_voice_id: str = Field(
        default="248be419-c632-4f23-adf1-5324ed7dbf1d", env="CARTESIA_VOICE_ID"
    )
    cartesia_model: str = Field(default="sonic-turbo", env="CARTESIA_MODEL")

    # Voice Processing Settings
    livekit_url: str = Field(default="ws://localhost:7880", env="LIVEKIT_URL")
    livekit_api_key: str = Field(default="", env="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="", env="LIVEKIT_API_SECRET")

    # Voice Pipeline Settings
    vad_threshold: float = Field(default=0.5, env="VAD_THRESHOLD")
    vad_min_speech_duration: float = Field(default=0.1, env="VAD_MIN_SPEECH_DURATION")
    vad_min_silence_duration: float = Field(default=0.3, env="VAD_MIN_SILENCE_DURATION")

    # Performance Settings
    audio_chunk_size_ms: int = Field(default=20, env="AUDIO_CHUNK_SIZE_MS")
    audio_buffer_size_ms: int = Field(default=100, env="AUDIO_BUFFER_SIZE_MS")
    max_concurrent_sessions: int = Field(default=100, env="MAX_CONCURRENT_SESSIONS")
    enable_metrics: bool = Field(default=True, env="ENABLE_METRICS")

    # Storage Configuration (NEW - Local Storage Option)
    storage_type: str = Field(default="local", env="STORAGE_TYPE")  # "local" or "minio"
    local_storage_path: str = Field(default="./data/uploads", env="LOCAL_STORAGE_PATH")
    allowed_file_types: List[str] = Field(
        default=[".pdf", ".docx", ".txt", ".doc"], env="ALLOWED_FILE_TYPES"
    )

    # MinIO Storage (Kept for compatibility)
    minio_endpoint: str = Field(default="localhost:9000", env="MINIO_ENDPOINT")
    minio_access_key: str = Field(default="minioadmin", env="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(default="minioadmin", env="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="documents", env="MINIO_BUCKET")
    minio_bucket_name: str = Field(default="documents", env="MINIO_BUCKET_NAME")
    minio_secure: bool = Field(default=False, env="MINIO_SECURE")

    # Document Processing Settings
    chunk_size: int = Field(default=1000, env="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, env="CHUNK_OVERLAP")
    max_file_size: int = Field(default=100 * 1024 * 1024, env="MAX_FILE_SIZE")  # 100MB

    # Voyage AI (Better embeddings)
    voyage_api_key: Optional[str] = Field(default=None, env="VOYAGE_API_KEY")
    voyage_model: str = Field(default="voyage-3-large", env="VOYAGE_MODEL")

    # Exa (Web search for pre-meeting research)
    exa_api_key: Optional[str] = Field(default=None, env="EXA_API_KEY")

    # Postmark (Email delivery for post-meeting summaries)
    postmark_api_key: Optional[str] = Field(default=None, env="POSTMARK_API_KEY")
    postmark_from_email: str = Field(
        default="meetings@example.com", env="POSTMARK_FROM_EMAIL"
    )

    # Neo4j (Knowledge Graph)
    neo4j_uri: str = Field(default="bolt://localhost:7687", env="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", env="NEO4J_USER")
    neo4j_password: str = Field(default="voicedoc123", env="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", env="NEO4J_DATABASE")
    neo4j_enabled: bool = Field(default=True, env="NEO4J_ENABLED")

    # Authentication
    api_key: Optional[str] = Field(default=None, env="API_KEY")
    require_api_key: bool = Field(default=False, env="REQUIRE_API_KEY")

    # JWT (user authentication)
    jwt_secret: str = Field(default="dev-secret-change-in-production", env="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", env="JWT_ALGORITHM")
    jwt_expiry_minutes: int = Field(default=1440, env="JWT_EXPIRY_MINUTES")
    # When true, meeting endpoints require a logged-in user (multi-tenant).
    # When false (dev/demo), auth is optional and meetings aren't owner-scoped.
    require_auth: bool = Field(default=False, env="REQUIRE_AUTH")

    # Durable job queue (Arq). When true, background work (agent dispatch,
    # research, summary) is enqueued to a durable Redis-backed queue and run
    # by the job worker (apps/workers/job_worker.py) with retries. When false
    # (dev/demo), work runs in-process via FastAPI BackgroundTasks.
    use_job_queue: bool = Field(default=False, env="USE_JOB_QUEUE")

    # Observability
    enable_tracing: bool = Field(default=False, env="ENABLE_TRACING")
    otlp_endpoint: str = Field(default="http://localhost:4317", env="OTLP_ENDPOINT")

    # Resilience
    allow_local_embedding_fallback: bool = Field(
        default=False, env="ALLOW_LOCAL_EMBEDDING_FALLBACK"
    )

    # Rate limiting
    rate_limit_upload: str = Field(default="5/minute", env="RATE_LIMIT_UPLOAD")
    rate_limit_query: str = Field(default="30/minute", env="RATE_LIMIT_QUERY")

    # Latency Targets
    target_stt_latency_ms: int = Field(default=100, env="TARGET_STT_LATENCY_MS")
    target_tts_latency_ms: int = Field(default=80, env="TARGET_TTS_LATENCY_MS")
    target_llm_latency_ms: int = Field(default=1000, env="TARGET_LLM_LATENCY_MS")
    target_total_latency_ms: int = Field(default=200, env="TARGET_TOTAL_LATENCY_MS")

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
