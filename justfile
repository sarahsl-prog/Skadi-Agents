# WolfPack development commands.

install:
    uv sync --all-extras --dev

fmt:
    uv run ruff format .

lint:
    uv run ruff check .

typecheck:
    uv run mypy

test:
    uv run pytest -q tests/unit

test-integration:
    uv run pytest -q tests/integration

# Start the full local stack (postgres, nats, otel-collector, ollama; mlflow in 'full' profile).
up:
    docker compose up -d

# Start with MLflow included.
up-full:
    docker compose --profile full up -d

down:
    docker compose --profile full down --remove-orphans

# Run the Phase 0 smoke test against the local stack.
smoke:
    uv run python -m wolfpack.smoke.hello_pack

# Start the Analyst Console API server.
api:
    uv run uvicorn wolfpack.api.app:create_app --factory --host 0.0.0.0 --port 8000 --reload

# Phase 7: run the learning-queue worker (one pass)
learning-worker:
    uv run python -m wolfpack.learning.worker

# Phase 7: run replay evaluation against case-history index
eval-replay:
    uv run python -m wolfpack.eval.replay

# Alembic migrations
migrate:
    uv run alembic upgrade head

migrate-create msg:
    uv run alembic revision -m "{{msg}}"