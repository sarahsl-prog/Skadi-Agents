#!/bin/bash
set -euo pipefail

echo "==> Installing Python dependencies via Poetry"
cd /workspace
poetry install --with dev

echo "==> Activating venv for path setup"
source .venv/bin/activate

echo "==> Installing LLM + security tools"
pip install --upgrade \
    pylint mypy black isort ruff \
    bandit safety pip-audit \
    semgrep \
    langchain langchain-anthropic \
    openai anthropic \
    rich typer httpx pydantic

echo "==> Configuring pylint"
cat > /workspace/.pylintrc << 'EOF'
[MASTER]
jobs=2

[FORMAT]
max-line-length=100

[MESSAGES CONTROL]
disable=C0114,C0115,C0116  # docstring warnings — adjust to taste

[DESIGN]
max-args=8
EOF

echo "==> Configuring bandit (security linter)"
cat > /workspace/.bandit.yaml << 'EOF'
targets: [src]
recursive: true
severity: medium
confidence: medium
EOF

echo "==> Validating AI CLI tools"
echo -n "Claude Code: "; claude --version 2>/dev/null || echo "not found - check npm install"
echo -n "OpenCode:    "; opencode --version 2>/dev/null || echo "not found - check install script"

echo "==> Running initial security audit"
pip-audit --desc 2>/dev/null || echo "pip-audit: no deps to audit yet"

echo "==> Container ready. You may now question your life choices in isolation."
