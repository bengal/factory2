#!/usr/bin/env bash
# With --userns=keep-id, the host UID maps directly to the container user,
# so workspace files have correct ownership. No chown needed.

# Set git identity and trust workspace directories
git config --global user.name "${GIT_AUTHOR_NAME:-Factory}" 2>/dev/null || true
git config --global user.email "${GIT_AUTHOR_EMAIL:-factory@localhost}" 2>/dev/null || true
git config --global --add safe.directory '*' 2>/dev/null || true

# Set up Qwen Code credentials if mounted
if [ -f /run/secrets/qwen-oauth-creds.json ]; then
    mkdir -p ~/.qwen
    cp /run/secrets/qwen-oauth-creds.json ~/.qwen/oauth_creds.json
    [ -f /run/secrets/qwen-settings.json ] && cp /run/secrets/qwen-settings.json ~/.qwen/settings.json
fi

# Fix git worktree absolute paths created on the host.
# A worktree's .git file contains "gitdir: /host/path/.git/worktrees/name"
# which doesn't exist inside the container. Rewrite to use /workspace.
project_dir="${1:-/workspace}"
for gitfile in "$project_dir"/.?*/.git "$project_dir"/*/.git; do
    [ -f "$gitfile" ] || continue
    gitdir=$(sed -n 's/^gitdir: //p' "$gitfile")
    [ -n "$gitdir" ] && [ ! -d "$gitdir" ] || continue

    wt_name=$(basename "$gitdir")
    new_gitdir="$project_dir/.git/worktrees/$wt_name"
    [ -d "$new_gitdir" ] || continue

    # Rewrite the worktree's .git pointer
    echo "gitdir: $new_gitdir" > "$gitfile"
    # Rewrite the back-reference so git can find the worktree
    echo "$gitfile" > "$new_gitdir/gitdir"
done

exec python3 -m factory "$@"
