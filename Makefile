.PHONY: test lint format db-up db-down db-reset migrate

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .
	uv run ruff check --fix .

db-up:
	docker compose up -d --build --wait db

db-down:
	docker compose down

# WARNING: deletes all stored data
db-reset:
	docker compose down -v

migrate:
	uv run python -m deskpilot.storage.migrate

api:
	uv run uvicorn deskpilot.api.app:create_app --factory --host 127.0.0.1 --port 8000