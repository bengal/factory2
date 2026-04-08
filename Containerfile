FROM rust:1.83-bookworm

# Install Node.js (required for Claude Code CLI) and Python
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    git \
    sudo \
    iproute2 \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Install Rust tooling
RUN rustup component add clippy rustfmt rust-analyzer

# Install coding agent CLIs and clean up caches to reduce image file count
RUN npm install -g @anthropic-ai/claude-code @qwen-code/qwen-code && \
    npm cache clean --force && \
    rm -rf /tmp/* /root/.npm /root/.cache

# Copy factory into image
COPY . /factory/
RUN chmod +x /factory/entrypoint.sh /factory/run_container.sh

# Claude CLI refuses --dangerously-skip-permissions as root.
# Create a non-root user with passwordless sudo.
# With --userns=keep-id, podman maps the host UID into the container.
# We create the factory user and allow ALL users passwordless sudo.
RUN useradd -m -s /bin/bash factory && \
    echo "ALL ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/factory

USER factory
ENV PATH="/usr/local/cargo/bin:${PATH}"
ENV NODE_COMPILE_CACHE=""

WORKDIR /workspace

ENTRYPOINT ["/factory/entrypoint.sh"]
