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
# /var/lib/shifty guarda el estado de los procesos de Celery: el schedule de
# beat (volumen beat_schedule; un volumen nuevo copia este dueno) y el archivo
# de latido del worker que mira su healthcheck (core/celery_app.py).
RUN useradd --system --create-home --uid 10001 appuser \
    && mkdir -p /var/lib/shifty/beat \
    && chown -R appuser:appuser /app /var/lib/shifty
USER appuser

# Environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Sin `uv run`: el entorno ya quedo resuelto por `uv sync --frozen --no-dev`
# y el PATH de arriba apunta a ese venv. `uv run` reconciliaba el proyecto
# en cada arranque contra /app, que en desarrollo era un bind-mount del host.
# --timeout-graceful-shutdown (F0-21): ante SIGTERM uvicorn deja de aceptar y
# espera a los requests en curso como mucho 30 s; compose le da 35 s
# (stop_grace_period) antes del SIGKILL, para que el lifespan cierre el pool.
# --no-access-log (F0-22): nginx ya registra cada request; el de uvicorn
# duplicaba cada linea y llevaba la query entera (client_phone incluido).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "30", "--no-access-log"]
