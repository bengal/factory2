FROM rust:1.86-bookworm

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

# Install coding agent CLIs
RUN npm install -g @anthropic-ai/claude-code @qwen-code/qwen-code && \
    npm cache clean --force && \
    rm -rf /tmp/* /root/.npm /root/.cache

# Strip ~25k files not needed at runtime.
# With --userns=keep-id podman chowns every file at startup; fewer files = faster.
RUN rm -rf \
    /usr/share/doc \
    /usr/share/man \
    /usr/share/locale \
    /usr/share/perl \
    /usr/share/perl5 \
    /usr/share/zoneinfo \
    /usr/share/mime \
    /usr/share/icons \
    /usr/share/X11 \
    /usr/include \
    /usr/lib/node_modules/npm \
    /usr/lib/python3/dist-packages \
    /usr/lib/python3.11/test \
    /usr/lib/python3.11/unittest \
    /usr/lib/python3.11/idlelib \
    /usr/lib/python3.11/tkinter \
    /usr/lib/python3.11/ensurepip \
    /usr/lib/gcc \
    /var/lib/dpkg \
    /var/lib/apt \
    /var/cache

# Copy factory into image
COPY . /factory/
RUN chmod +x /factory/entrypoint.sh /factory/run_container.sh

# Claude CLI refuses --dangerously-skip-permissions as root.
# Create a non-root user with passwordless sudo for network operations.
# With --userns=keep-id, podman maps the host UID (1000) to this user,
# so mounted volumes have correct ownership on both sides.
RUN useradd -m -s /bin/bash factory && \
    echo "ALL ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/factory

USER factory
ENV PATH="/usr/local/cargo/bin:${PATH}"
ENV NODE_COMPILE_CACHE=""

WORKDIR /workspace

ENTRYPOINT ["/factory/entrypoint.sh"]
