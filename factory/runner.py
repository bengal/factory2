import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import log


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


def run_claude(
    prompt: str,
    log_file: Path,
    model: str,
    max_turns: int,
    workdir: Path,
    claude_cmd: str = "claude",
    skip_permissions: bool = True,
    verbose: bool = False,
) -> tuple[bool, Usage]:
    """Run Claude Code in print mode. Returns (success, usage)."""

    cmd = [
        claude_cmd,
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
    ]

    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    # Pass prompt via stdin to avoid "Argument list too long" with large prompts
    cmd.append("-")

    log.info(f"  Claude: model={model} max_turns={max_turns}")
    log.info(f"  Log:    {log_file}")

    log_file.parent.mkdir(parents=True, exist_ok=True)

    usage = Usage()

    with open(log_file, "w") as lf:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=workdir,
            text=True,
        )
        proc.stdin.write(prompt)
        proc.stdin.close()

        for line in proc.stdout:
            lf.write(line)
            lf.flush()

            if verbose:
                sys.stderr.write(line)

            # Parse stream-json for usage stats
            stripped = line.strip()
            if stripped:
                _accumulate_usage(stripped, usage)

        proc.wait()

    if proc.returncode != 0:
        log.error(f"  Claude exited with code {proc.returncode}")

    return proc.returncode == 0, usage


def _accumulate_usage(line: str, usage: Usage):
    """Extract token counts from a stream-json line."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return

    u = _find_usage(obj)
    if not u:
        return

    # Stream-json reports cumulative usage — keep the max seen
    usage.input_tokens = max(usage.input_tokens, u.get("input_tokens", 0))
    usage.output_tokens = max(usage.output_tokens, u.get("output_tokens", 0))
    usage.cache_creation_tokens = max(
        usage.cache_creation_tokens, u.get("cache_creation_input_tokens", 0)
    )
    usage.cache_read_tokens = max(
        usage.cache_read_tokens, u.get("cache_read_input_tokens", 0)
    )


def _find_usage(obj) -> dict | None:
    """Recursively search a JSON object for a usage dict with input_tokens."""
    if isinstance(obj, dict):
        if "input_tokens" in obj and "output_tokens" in obj:
            return obj
        for v in obj.values():
            result = _find_usage(v)
            if result:
                return result
    if isinstance(obj, list):
        for item in obj:
            result = _find_usage(item)
            if result:
                return result
    return None
