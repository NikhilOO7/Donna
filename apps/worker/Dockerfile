# LiveKit Voice Worker Dockerfile
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    libpq-dev \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install Python dependencies
RUN uv sync --no-dev

# Download spaCy English model
RUN uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# Copy application code
COPY apps/api ./apps/api
COPY apps/__init__.py ./apps/

# Create necessary directories
RUN mkdir -p logs data

# Expose port (if needed for health checks)
EXPOSE 8001

# Run the LiveKit voice worker
CMD ["uv", "run", "python", "-m", "apps.api.services.voice.enhanced_livekit_service"]
