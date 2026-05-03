#!/bin/bash
set -euo pipefail

echo "==> Installing Python dependencies via uv"
cd /workspace
uv sync --all-extras --dev

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
uv run pip-audit --desc 2>/dev/null || echo "pip-audit: no deps to audit yet"

echo "==> Container ready. You may now question your life choices in isolation."
