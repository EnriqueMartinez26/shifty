.PHONY: dev test migrate makemigrations build down clean shell

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
# existiria dentro del contenedor.
# - Se lista /app/alembic/versions ANTES de generar y se copia solo lo nuevo.
# - Si el contenedor tiene una revision que el host no, se aborta sin generar:
#   es una revision descartada en el host que la nueva tomaria como head.
#   Despues de descartar una revision, reconstruir el backend (`make build` y
#   recrear el contenedor, p. ej. `make dev`).
# - Nunca se pisa un archivo del host (una migracion editada despues del build).
makemigrations:
	@set -e; \
	versiones=backend/alembic/versions; \
	antes=$$(docker compose exec -T backend ls -1 /app/alembic/versions); \
	for f in $$antes; do \
		case "$$f" in *.py) ;; *) continue ;; esac; \
		[ -e "$$versiones/$$f" ] || { \
			echo "El contenedor tiene $$f y el host no (revision descartada?)." >&2; \
			echo "Reconstruir el backend (make build y recrear el contenedor) y reintentar." >&2; \
			exit 1; }; \
	done; \
	docker compose exec -T backend alembic revision --autogenerate -m "$(name)"; \
	despues=$$(docker compose exec -T backend ls -1 /app/alembic/versions); \
	for f in $$despues; do \
		case "$$f" in *.py) ;; *) continue ;; esac; \
		case " $$(echo $$antes) " in *" $$f "*) continue ;; esac; \
		[ -e "$$versiones/$$f" ] || docker compose cp "backend:/app/alembic/versions/$$f" "$$versiones/$$f"; \
	done

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
