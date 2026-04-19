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