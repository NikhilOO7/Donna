# FastAPI Backend Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files and README (required by hatchling build)
COPY pyproject.toml uv.lock* README.md ./

# Install Python dependencies
RUN uv sync --no-dev

# Download spaCy English model
RUN uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# Copy application code
COPY apps/api ./apps/api
COPY apps/__init__.py ./apps/

# Create necessary directories
RUN mkdir -p logs data static

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Apply DB migrations, then run the application. The schema is owned by
# Alembic (no implicit create_all). For a multi-replica deployment, prefer
# running `alembic upgrade head` as a dedicated pre-deploy job and drop the
# migration step here so replicas don't race on startup.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"]
