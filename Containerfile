FROM fedora:42

# Install Rust toolchain, RPM build tooling, and system packages
RUN dnf install -y \
    rust cargo clippy rustfmt sccache dnsmasq util-linux \
    rpm-build rpmlint cargo-rpm-macros systemd-rpm-macros \
    nodejs npm \
    python3 \
    jq git sudo which \
    iproute iptables-nft \
    gcc \
    && dnf clean all

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
    /usr/share/perl5 \
    /usr/share/zoneinfo \
    /usr/share/mime \
    /usr/share/icons \
    /usr/share/X11 \
    /usr/include \
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
ENV NODE_COMPILE_CACHE=""
ENV RUSTC_WRAPPER=sccache

WORKDIR /workspace

ENTRYPOINT ["/factory/entrypoint.sh"]
