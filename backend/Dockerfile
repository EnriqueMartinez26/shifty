FROM python:3.14.7-slim-trixie

# Install system dependencies
# `apt-get upgrade`: esta capa se cachea (cache gha de build-images.yml) y
# dejaba paquetes con avisos de seguridad ya corregidos en trixie-security
# (linux-libc-dev, openssl/libssl). Cada build que reconstruye la capa los trae.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Sin el pip del sistema: la app corre del .venv de uv (que no trae pip) y nada
# lo usa en runtime. pip 26.2.1 publica un SBOM (pip/_vendor/bom.cdx.json) con
# msgpack 1.1.2 y setuptools 70.3.0 vendorizados (GHSA-6v7p-g79w-8964,
# CVE-2025-47273) y al 2026-09-26 no hay pip que los actualice.
RUN python -m pip uninstall --yes pip

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
