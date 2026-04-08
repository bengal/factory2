#!/usr/bin/env bash
# Fix workspace ownership (may be root-owned from a previous run or host mount)
# then exec the factory as the current user.
sudo chown -R "$(id -u):$(id -g)" /workspace 2>/dev/null || true

# Set git identity if not configured
git config --global user.name "${GIT_AUTHOR_NAME:-Factory}" 2>/dev/null || true
git config --global user.email "${GIT_AUTHOR_EMAIL:-factory@localhost}" 2>/dev/null || true

# Set up Qwen Code credentials if provided in workspace
if [ -f /workspace/.qwen-oauth-creds.json ]; then
    mkdir -p ~/.qwen
    cp /workspace/.qwen-oauth-creds.json ~/.qwen/oauth_creds.json
    [ -f /workspace/.qwen-settings.json ] && cp /workspace/.qwen-settings.json ~/.qwen/settings.json
fi

exec python3 -m factory "$@"
