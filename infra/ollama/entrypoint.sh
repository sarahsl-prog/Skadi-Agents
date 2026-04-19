#!/usr/bin/env bash
# WolfPack Ollama entrypoint.
# Starts the Ollama server and pre-pulls the dev smoke model on first run.

set -euo pipefail

# Default smoke model; override with OLLAMA_SMOKETEST_MODEL env var.
SMOKE_MODEL="${OLLAMA_SMOKETEST_MODEL:-llama3.2:1b}"

# Start Ollama in the background so we can pull while it serves.
ollama serve &
SERVER_PID=$!

# Wait until the API is responsive.
RETRIES=30
until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    if [ "$RETRIES" -le 0 ]; then
        echo "Ollama API did not become ready in time" >&2
        exit 1
    fi
    sleep 1
done

# Pull the dev model (idempotent — no-op if already present).
echo "Pulling smoke model: ${SMOKE_MODEL}"
ollama pull "${SMOKE_MODEL}" || echo "WARN: could not pull ${SMOKE_MODEL}; smoke test may fail"

# Forward signals and wait for the server.
wait "$SERVER_PID"