#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: monitor.sh [OPTIONS] <workspace> [mode] [story-id]

Monitor a running factory.

Arguments:
  workspace              Path to the workspace directory
  mode                   status (live, default), once (snapshot), tail (log stream)
  story-id               Filter tail output to a specific story

Options:
  -h, --help             Show this help

Examples:
  ./monitor.sh ./factory-output/workspace
  ./monitor.sh ./factory-output/workspace once
  ./monitor.sh ./factory-output/workspace tail 01-network-api
EOF
    exit 0
}

if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
fi

exec python3 -m factory.monitor "$@"
