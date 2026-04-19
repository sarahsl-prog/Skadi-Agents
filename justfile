set shell := ["powershell.exe", "-NoLogo", "-Command"]

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

up:
    docker compose up -d

down:
    docker compose down --remove-orphans

smoke:
    uv run python -m wolfpack.smoke.hello_pack
