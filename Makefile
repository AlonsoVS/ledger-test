.PHONY: up down migrate run test lint format typecheck check

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	uv run alembic upgrade head

run:
	uv run uvicorn ledger.api.app:app --reload

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

check: lint typecheck test
