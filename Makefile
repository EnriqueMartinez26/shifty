.PHONY: dev test migrate build down clean shell

# El codigo sale de la imagen (no hay bind mount del host): un cambio en
# backend/ o frontend/ exige reconstruir, y `up --build` lo hace.
dev:
	DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build

down:
	docker compose down

build:
	DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build

# Aplica las migraciones que trae la imagen: una migracion nueva exige
# reconstruir antes (`make build` o `make dev`).
migrate:
	docker compose exec backend alembic upgrade head

# La revision se genera en el contenedor, contra los modelos de la imagen
# (reconstruir antes si cambiaron), y se copia al host: sin bind mount solo
# existiria dentro del contenedor. Se copian solo los archivos que el host no
# tiene, para no pisar una migracion editada en el host despues del build.
makemigrations:
	docker compose exec backend alembic revision --autogenerate -m "$(name)"
	rm -rf .makemigrations-tmp
	docker compose cp backend:/app/alembic/versions .makemigrations-tmp
	for f in .makemigrations-tmp/*.py; do \
		[ -e "backend/alembic/versions/$$(basename "$$f")" ] || cp "$$f" backend/alembic/versions/; \
	done
	rm -rf .makemigrations-tmp

# pytest corre en el host: la imagen no trae tests/ (backend/.dockerignore) y
# se construye con `uv sync --frozen --no-dev`, sin pytest ni ipython (grupo
# `dev` de pyproject.toml). `--frozen` evita que uv re-resuelva y reescriba
# uv.lock.
test:
	cd backend && uv run --frozen --group dev pytest

shell:
	docker compose exec backend uv run --frozen --group dev ipython

clean:
	docker compose down -v
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
