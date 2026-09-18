.PHONY: dev test migrate build down clean shell

# --renew-anon-volumes: /app/.venv es un volumen anonimo y sin esto el
# contenedor sigue con el venv viejo aunque la imagen traiga una dependencia
# nueva (CLAUDE.md §1).
dev:
	DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build --renew-anon-volumes

down:
	docker compose down

build:
	DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build

migrate:
	docker compose exec backend alembic upgrade head

makemigrations:
	docker compose exec backend alembic revision --autogenerate -m "$(name)"

# pytest e ipython viven en el grupo `dev` de pyproject.toml y la imagen se
# construye con `uv sync --frozen --no-dev`: sin `--group dev` estos dos
# atajos morian con "executable file not found in PATH". `--frozen` evita que
# uv re-resuelva y reescriba uv.lock, que aca es el del host (bind-mount).
test:
	docker compose exec backend uv run --frozen --group dev pytest

shell:
	docker compose exec backend uv run --frozen --group dev ipython

clean:
	docker compose down -v
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
