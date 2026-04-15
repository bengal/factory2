import argparse
import os
import sys
from pathlib import Path

from .config import Config
from .orchestrator import run_factory


def main():
    parser = argparse.ArgumentParser(
        prog="factory",
        description="AI Software Factory — turns user stories into working Rust code.",
    )
    parser.add_argument(
        "workspace", type=Path,
        help="Workspace directory containing a specs/ subdirectory with .md user stories",
    )
    parser.add_argument(
        "-j", "--parallel", type=int, default=1,
        help="Max parallel story pipelines (default: 1)",
    )
    parser.add_argument(
        "-r", "--retries", type=int, default=3,
        help="Max verify fix attempts per story (default: 3)",
    )
    parser.add_argument(
        "--strong-model", default=None,
        help="Model for plan + implement (default: auto per backend)",
    )
    parser.add_argument(
        "--default-model", default=None,
        help="Model for understand, write-tests, verify (default: auto per backend)",
    )
    parser.add_argument(
        "--fast-model", default=None,
        help="Model for dep analysis + summary (default: auto per backend)",
    )
    parser.add_argument(
        "--max-turns", type=int, default=100,
        help="Max turns per agent run (default: 100)",
    )
    parser.add_argument(
        "--verify-turns", type=int, default=120,
        help="Max turns for verify phase (default: 120)",
    )
    parser.add_argument(
        "--backend", choices=["claude", "qwen"], default="claude",
        help="Coding agent backend (default: claude)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Stream agent output to terminal in real time",
    )
    parser.add_argument(
        "--rerun", nargs="+", metavar="STORY",
        help="Force reprocessing of the given story IDs (resets their status and phases)",
    )
    parser.add_argument(
        "--llm-deps", action="store_true",
        help="Use LLM to analyze dependencies instead of parsing from spec files",
    )
    parser.add_argument(
        "--git-author-name", default=None,
        help="Git author name for commits (default: $GIT_AUTHOR_NAME or 'Factory')",
    )
    parser.add_argument(
        "--git-author-email", default=None,
        help="Git author email for commits (default: $GIT_AUTHOR_EMAIL or 'factory@localhost')",
    )

    args = parser.parse_args()

    backend = args.backend
    default_cmd = "qwen" if backend == "qwen" else "claude"
    cmd = os.environ.get("FACTORY_CMD", os.environ.get("CLAUDE_CMD", default_cmd))

    # Model defaults per backend — Config dataclass has per-tier defaults for claude;
    # for qwen, collapse everything to the single qwen model name.
    model_overrides = {}
    if backend == "qwen":
        qwen_model = "coder-model"
        model_overrides = dict(strong_model=qwen_model, default_model=qwen_model, fast_model=qwen_model)

    config = Config(
        workspace=args.workspace.resolve(),
        max_parallel=args.parallel,
        max_retries=args.retries,
        strong_model=args.strong_model or model_overrides.get("strong_model", Config.strong_model),
        default_model=args.default_model or model_overrides.get("default_model", Config.default_model),
        fast_model=args.fast_model or model_overrides.get("fast_model", Config.fast_model),
        max_turns=args.max_turns,
        verify_turns=args.verify_turns,
        verbose=args.verbose,
        backend=backend,
        cmd=cmd,
        skip_permissions=os.environ.get("SKIP_PERMISSIONS", "1") == "1",
        rerun=args.rerun or [],
        llm_deps=args.llm_deps,
        git_author_name=args.git_author_name or os.environ.get("GIT_AUTHOR_NAME", "Factory"),
        git_author_email=args.git_author_email or os.environ.get("GIT_AUTHOR_EMAIL", "factory@localhost"),
    )

    try:
        run_factory(config)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
