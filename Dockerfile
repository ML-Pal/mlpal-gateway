# syntax=docker/dockerfile:1

# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files (include the lockfile for reproducible installs)
COPY pyproject.toml uv.lock README.md ./

# Install the EXACT locked dependency versions instead of resolving fresh from
# pyproject constraints. Fresh resolution silently drifted prod to newer SDKs on
# every rebuild (e.g. google-genai 1.x→2.x changed Gemini tool/thinking behavior).
# The project code itself is provided via PYTHONPATH in the runtime stage.
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    uv pip install --system --no-cache -r /tmp/requirements.txt

# Runtime stage
FROM python:3.11-slim as runtime

WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .
# Version metadata for /v1/catalog/feed (the project itself isn't pip-installed)
COPY pyproject.toml .
# Seed + bootstrap scripts (used by the docker-compose migrate/seed init
# containers for self-hosted setup). Harmless in the managed image.
COPY scripts/ ./scripts/
COPY config/ ./config/

# Set ownership
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health/live')" || exit 1

# Run the application
CMD ["uvicorn", "mlpal_assistants_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
