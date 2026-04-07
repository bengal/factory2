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
        "--strong-model", default="claude-sonnet-4-6",
        help="Model for plan + implement (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--default-model", default="claude-sonnet-4-6",
        help="Model for understand, write-tests, verify (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--fast-model", default="claude-sonnet-4-6",
        help="Model for dep analysis + summary (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--max-turns", type=int, default=80,
        help="Max turns per Claude run (default: 80)",
    )
    parser.add_argument(
        "--verify-turns", type=int, default=120,
        help="Max turns for verify phase (default: 120)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Stream Claude output to terminal in real time",
    )

    args = parser.parse_args()

    config = Config(
        workspace=args.workspace.resolve(),
        max_parallel=args.parallel,
        max_retries=args.retries,
        strong_model=args.strong_model,
        default_model=args.default_model,
        fast_model=args.fast_model,
        max_turns=args.max_turns,
        verify_turns=args.verify_turns,
        verbose=args.verbose,
        claude_cmd=os.environ.get("CLAUDE_CMD", "claude"),
        skip_permissions=os.environ.get("SKIP_PERMISSIONS", "1") == "1",
    )

    try:
        run_factory(config)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
