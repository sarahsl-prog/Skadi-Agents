FROM python:3.11-slim-bookworm

ARG USERNAME=devuser
ARG USER_UID=1000
ARG USER_GID=${USER_UID}

# System deps + security tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ca-certificates gnupg \
    build-essential libssl-dev libffi-dev \
    nodejs npm docker.io docker-compose \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (because running as root is a cry for help)
RUN groupadd --gid ${USER_GID} ${USERNAME} \
    && useradd --uid ${USER_UID} --gid ${USER_GID} \
       -m -s /bin/bash ${USERNAME} \
    && mkdir -p /home/${USERNAME}/.vscode-server/extensions \
    && mkdir -p /home/${USERNAME}/.cache/uv \
    && chown -R ${USERNAME}:${USERNAME} /home/${USERNAME} \
    && usermod -aG docker ${USERNAME}

# Install uv (fast Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

# Node globals for AI CLI tools
RUN npm install -g @anthropic-ai/claude-code@latest

# OpenCode CLI (tarball release from sst/opencode)
RUN curl -fsSL -o /tmp/opencode.tar.gz \
      https://github.com/sst/opencode/releases/latest/download/opencode-linux-x64.tar.gz \
    && tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin \
    && chmod +x /usr/local/bin/opencode \
    && rm /tmp/opencode.tar.gz

# Drop to non-root
USER ${USERNAME}
WORKDIR /workspace
