FROM python:3.14.6-slim-trixie

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /uvx /bin/

WORKDIR /app

# Copy dependency metadata, including the lockfile for reproducible installs
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Usuario no-root: si un atacante logra ejecucion, no arranca como root dentro
# del contenedor. Se le da la propiedad de /app (incluye el .venv).
RUN useradd --system --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Sin `uv run`: el entorno ya quedo resuelto por `uv sync --frozen --no-dev`
# y el PATH de arriba apunta a ese venv. `uv run` reconciliaba el proyecto
# en cada arranque contra /app, que en desarrollo era un bind-mount del host.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
