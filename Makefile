.PHONY: dev test migrate build down clean shell

dev:
	docker-compose up --build

down:
	docker-compose down

build:
	docker-compose build

migrate:
	docker-compose exec backend alembic upgrade head

makemigrations:
	docker-compose exec backend alembic revision --autogenerate -m "$(name)"

test:
	docker-compose exec backend pytest

shell:
	docker-compose exec backend ipython

clean:
	docker-compose down -v
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
