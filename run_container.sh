#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: run_container.sh [OPTIONS] <specs-dir> [-- factory-options...]

Run the AI software factory inside a container.

Arguments:
  specs-dir                Directory containing .md user story specifications

Options:
  -o, --output DIR         Output/workspace directory (default: ./factory-output)
  -i, --image NAME         Container image name (default: factory2)
  -b, --build              Force rebuild the container image
  -R, --runtime CMD        Container runtime: docker or podman (default: auto-detect)
  -h, --help               Show this help

Everything after -- is passed through to the factory.

Factory options:
  -j, --parallel N         Max parallel story pipelines (default: 1)
  -r, --retries N          Max verify fix attempts per story (default: 3)
  --strong-model MODEL     Model for plan phase (default: claude-opus-4-6)
  --default-model MODEL    Model for understand, implement, write-tests, verify (default: claude-sonnet-4-6)
  --fast-model MODEL       Model for dep analysis, summary, commit messages (default: claude-haiku-4-5)
  --max-turns N            Max turns per agent run (default: 100)
  --verify-turns N         Max turns for verify phase (default: 120)
  -v, --verbose            Stream agent output to terminal in real time
  --rerun STORY [...]      Force reprocessing of specific stories

Authentication: set EITHER Anthropic API key OR Vertex AI env vars before running.
For Qwen backend, run 'qwen auth' once locally; credentials in ~/.qwen/ are auto-copied.

  # Anthropic API (claude backend)
  export ANTHROPIC_API_KEY="sk-ant-..."

  # OR Vertex AI (claude backend)
  export CLAUDE_CODE_USE_VERTEX=1
  export CLOUD_ML_REGION=us-east5
  export ANTHROPIC_VERTEX_PROJECT_ID=my-project

  # OR Qwen (qwen backend — uses ~/.qwen/oauth_creds.json)
  export FACTORY_BACKEND=qwen

Examples:
  ./run_container.sh ./my-specs
  ./run_container.sh ./my-specs -- -j 4 --strong-model claude-opus-4-6
  ./run_container.sh ./my-specs -o ./output -- -v --fast-model claude-haiku-4-5-20251001
  FACTORY_BACKEND=qwen ./run_container.sh ./my-specs -- --model qwen3-coder-plus
EOF
    exit 0
}

# ─── Defaults ────────────────────────────────────────────────────────

OUTPUT_DIR="./factory-output"
IMAGE_NAME="factory2"
FORCE_BUILD=false
RUNTIME=""
SPECS_DIR=""
FACTORY_ARGS=()
BACKEND="${FACTORY_BACKEND:-claude}"

# ─── Parse Args ──────────────────────────────────────────────────────

while [ $# -gt 0 ]; do
    case "$1" in
        -o|--output)   OUTPUT_DIR="$2"; shift 2 ;;
        -i|--image)    IMAGE_NAME="$2"; shift 2 ;;
        -b|--build)    FORCE_BUILD=true; shift ;;
        -R|--runtime)  RUNTIME="$2"; shift 2 ;;
        -h|--help)     usage ;;
        --)            shift; FACTORY_ARGS=("$@"); break ;;
        -*)            echo "ERROR: Unknown option: $1" >&2; usage ;;
        *)
            if [ -z "$SPECS_DIR" ]; then
                SPECS_DIR="$1"; shift
            else
                echo "ERROR: Unexpected argument: $1" >&2; usage
            fi
            ;;
    esac
done

if [ -z "$SPECS_DIR" ]; then
    echo "ERROR: specs-dir is required" >&2
    usage
fi

SPECS_DIR="$(cd "$SPECS_DIR" && pwd)"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

# ─── Detect Container Runtime ───────────────────────────────────────

if [ -z "$RUNTIME" ]; then
    if command -v podman &>/dev/null; then
        RUNTIME="podman"
    elif command -v docker &>/dev/null; then
        RUNTIME="docker"
    else
        echo "ERROR: No container runtime found. Install podman or docker." >&2
        exit 1
    fi
fi

echo "Using container runtime: $RUNTIME"

# ─── Build Image ────────────────────────────────────────────────────

image_exists() {
    $RUNTIME image inspect "$IMAGE_NAME" &>/dev/null 2>&1
}

if $FORCE_BUILD || ! image_exists; then
    echo "Building container image '$IMAGE_NAME'..."
    $RUNTIME build -t "$IMAGE_NAME" "$SCRIPT_DIR"
fi

# ─── Validate Environment ───────────────────────────────────────────

if [ "$BACKEND" = "qwen" ]; then
    if [ ! -f "${HOME}/.qwen/oauth_creds.json" ] && [ -z "${DASHSCOPE_API_KEY:-}" ]; then
        echo "ERROR: Qwen backend requires either ~/.qwen/oauth_creds.json (run 'qwen auth') or DASHSCOPE_API_KEY" >&2
        exit 1
    fi
elif [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_CODE_USE_VERTEX:-}" ]; then
    echo "ERROR: Set ANTHROPIC_API_KEY or Vertex AI env vars (CLAUDE_CODE_USE_VERTEX, CLOUD_ML_REGION, ANTHROPIC_VERTEX_PROJECT_ID)" >&2
    exit 1
fi

# ─── Build auth-related container args ──────────────────────────────

AUTH_ARGS=()
cred_src=""

if [ "$BACKEND" = "qwen" ]; then
    # Qwen credentials are copied into workspace below (after mkdir).
    # Pass API key if set (alternative to OAuth).
    [ -n "${DASHSCOPE_API_KEY:-}" ] && AUTH_ARGS+=(-e DASHSCOPE_API_KEY)
elif [ -n "${CLAUDE_CODE_USE_VERTEX:-}" ]; then
    AUTH_ARGS+=(-e CLAUDE_CODE_USE_VERTEX)
    AUTH_ARGS+=(-e CLOUD_ML_REGION)
    AUTH_ARGS+=(-e ANTHROPIC_VERTEX_PROJECT_ID)

    # Pass through optional Vertex env vars
    [ -n "${ANTHROPIC_VERTEX_REGION:-}" ]    && AUTH_ARGS+=(-e ANTHROPIC_VERTEX_REGION)

    # Credentials are copied into the workspace after it's created (see below).
    if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]; then
        cred_src="${GOOGLE_APPLICATION_CREDENTIALS}"
    elif [ -f "${HOME}/.config/gcloud/application_default_credentials.json" ]; then
        cred_src="${HOME}/.config/gcloud/application_default_credentials.json"
    else
        echo "WARN: No GCP credentials found. The container will rely on metadata-server / workload identity." >&2
    fi
else
    AUTH_ARGS+=(-e ANTHROPIC_API_KEY)
fi

# ─── Prepare Workspace ──────────────────────────────────────────────

WORKSPACE="$OUTPUT_DIR"
mkdir -p "$WORKSPACE/specs"

# Reclaim ownership from previous container runs that used subuid remapping.
# With --userns=keep-id this is only needed once to migrate old workspaces.
if [ "$RUNTIME" = "podman" ]; then
    $RUNTIME unshare chown -R 0:0 "$WORKSPACE" 2>/dev/null || true
fi

# Snapshot current specs before overwriting (used by triage to compute diffs)
rm -rf "$WORKSPACE/.specs-prev"
if ls "$WORKSPACE/specs/"*.md &>/dev/null; then
    mkdir -p "$WORKSPACE/.specs-prev"
    cp "$WORKSPACE/specs/"*.md "$WORKSPACE/.specs-prev/"
fi

# Sync specs into workspace: copy new/updated specs, remove deleted ones.
cp "$SPECS_DIR"/*.md "$WORKSPACE/specs/" || {
    echo "ERROR: No .md files found in $SPECS_DIR" >&2
    exit 1
}
# Remove workspace specs that no longer exist in the source directory
for f in "$WORKSPACE/specs/"*.md; do
    [ -f "$f" ] || continue
    if [ ! -f "$SPECS_DIR/$(basename "$f")" ]; then
        echo "Removing deleted spec: $(basename "$f")"
        rm "$f"
    fi
done

# Copy credentials into workspace (with --userns=keep-id, ownership is preserved).
if [ -n "${cred_src:-}" ]; then
    cp "$cred_src" "$WORKSPACE/.gcp-credentials.json"
    AUTH_ARGS+=(-e GOOGLE_APPLICATION_CREDENTIALS=/workspace/.gcp-credentials.json)
fi

# Copy Qwen OAuth credentials into workspace
if [ "$BACKEND" = "qwen" ] && [ -f "${HOME}/.qwen/oauth_creds.json" ]; then
    cp "${HOME}/.qwen/oauth_creds.json" "$WORKSPACE/.qwen-oauth-creds.json"
    [ -f "${HOME}/.qwen/settings.json" ] && cp "${HOME}/.qwen/settings.json" "$WORKSPACE/.qwen-settings.json"
fi

# ─── Run ─────────────────────────────────────────────────────────────

echo ""
echo "Starting factory..."
echo "  Specs:       $SPECS_DIR"
echo "  Workspace:   $WORKSPACE"
echo "  Backend:     $BACKEND"
echo "  Runtime:     $RUNTIME"
echo "  Image:       $IMAGE_NAME"
echo ""

# Inject --backend into factory args
FACTORY_ARGS=("--backend" "$BACKEND" "${FACTORY_ARGS[@]+"${FACTORY_ARGS[@]}"}")

# Remove stale container with this name (from a previous interrupted run)
$RUNTIME rm -f factory2-run 2>/dev/null || true

USERNS_ARGS=()
if [ "$RUNTIME" = "podman" ]; then
    # Map host UID into container so files have correct ownership on both sides.
    # No more subuid remapping, no post-run chown needed.
    USERNS_ARGS=(--userns=keep-id)
fi

$RUNTIME run --rm \
    --name factory2-run \
    --cap-add=NET_ADMIN \
    --cap-add=SYS_ADMIN \
    "${USERNS_ARGS[@]+"${USERNS_ARGS[@]}"}" \
    -v "$WORKSPACE:/workspace" \
    "${AUTH_ARGS[@]}" \
    -e SKIP_PERMISSIONS="${SKIP_PERMISSIONS:-1}" \
    -e PYTHONPATH=/factory \
    "$IMAGE_NAME" \
    /workspace "${FACTORY_ARGS[@]+"${FACTORY_ARGS[@]}"}"

echo ""
echo "Factory complete."
echo "  Results:   $WORKSPACE/output/"
echo "  Project:   $WORKSPACE/project/"
echo "  State:     $WORKSPACE/state.json"
