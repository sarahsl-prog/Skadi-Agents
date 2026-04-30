FROM python:3.12-slim-bookworm

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

# Poetry - install as root, available system-wide
ENV POETRY_VERSION=1.8.3
ENV POETRY_HOME=/opt/poetry
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
ENV POETRY_NO_INTERACTION=1
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:${PATH}"

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
