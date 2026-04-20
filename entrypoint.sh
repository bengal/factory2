#!/usr/bin/env bash
# With --userns=keep-id, the host UID maps directly to the container user,
# so workspace files have correct ownership. No chown needed.

# Set git identity and trust workspace directories
git config --global user.name "${GIT_AUTHOR_NAME:-Factory}" 2>/dev/null || true
git config --global user.email "${GIT_AUTHOR_EMAIL:-factory@localhost}" 2>/dev/null || true
git config --global --add safe.directory /workspace 2>/dev/null || true

# Set up Qwen Code credentials if mounted
if [ -f /run/secrets/qwen-oauth-creds.json ]; then
    mkdir -p ~/.qwen
    cp /run/secrets/qwen-oauth-creds.json ~/.qwen/oauth_creds.json
    [ -f /run/secrets/qwen-settings.json ] && cp /run/secrets/qwen-settings.json ~/.qwen/settings.json
fi

exec python3 -m factory "$@"
