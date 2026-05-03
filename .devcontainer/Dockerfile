FROM python:3.11-slim-bookworm

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

# System deps + security tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ca-certificates gnupg \
    build-essential libssl-dev libffi-dev \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (because running as root is a cry for help)
RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} \
       -m -s /bin/bash ${USERNAME} \
    && mkdir -p /home/${USERNAME}/.vscode-server/extensions \
    && chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

# Node globals for AI CLI tools
RUN npm install -g @anthropic-ai/claude-code@latest

# OpenCode - go binary
RUN curl -fsSL https://opencode.ai/install.sh | sh 2>/dev/null || \
    wget -qO /usr/local/bin/opencode \
      https://github.com/sst/opencode/releases/latest/download/opencode-linux-x86_64 \
    && chmod +x /usr/local/bin/opencode

# Drop to non-root
USER ${USERNAME}
WORKDIR /workspace
