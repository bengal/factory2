#!/usr/bin/env bash
# Fix workspace ownership (may be root-owned from a previous run or host mount)
# then exec the factory as the current user.
sudo chown -R "$(id -u):$(id -g)" /workspace 2>/dev/null || true

# Set git identity if not configured
git config --global user.name "${GIT_AUTHOR_NAME:-Factory}" 2>/dev/null || true
git config --global user.email "${GIT_AUTHOR_EMAIL:-factory@localhost}" 2>/dev/null || true

exec python3 -m factory "$@"
