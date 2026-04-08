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
    num_turns: int = 0


def run_agent(
    prompt: str,
    log_file: Path,
    model: str,
    max_turns: int,
    workdir: Path,
    backend: str = "claude",
    cmd: str = "claude",
    skip_permissions: bool = True,
    verbose: bool = False,
) -> tuple[bool, Usage]:
    """Run a coding agent CLI in print mode. Returns (success, usage)."""

    if backend == "qwen":
        cmd_list = _build_qwen_cmd(cmd, model, max_turns, skip_permissions)
    else:
        cmd_list = _build_claude_cmd(cmd, model, max_turns, skip_permissions)

    log.info(f"  Agent ({backend}): model={model} max_turns={max_turns}")
    log.info(f"  Log:    {log_file}")

    log_file.parent.mkdir(parents=True, exist_ok=True)

    usage = Usage()

    with open(log_file, "w") as lf:
        proc = subprocess.Popen(
            cmd_list,
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

            # Parse stream-json for usage stats and turn count
            stripped = line.strip()
            if stripped:
                _accumulate_usage(stripped, usage)
                _accumulate_turns(stripped, usage)

        proc.wait()

    if proc.returncode != 0:
        log.error(f"  Agent exited with code {proc.returncode}")

    return proc.returncode == 0, usage


def _build_claude_cmd(cmd, model, max_turns, skip_permissions):
    args = [
        cmd,
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
    ]
    if skip_permissions:
        args.append("--dangerously-skip-permissions")
    args.append("-")  # read prompt from stdin
    return args


def _build_qwen_cmd(cmd, model, max_turns, skip_permissions):
    args = [
        cmd,
        "-p", "-",  # read prompt from stdin
        "--output-format", "stream-json",
        "--model", model,
        "--max-session-turns", str(max_turns),
        "--allowed-tools",
        "read_file", "write_file", "edit", "glob",
        "grep_search", "run_shell_command",
    ]
    if skip_permissions:
        args.append("--yolo")
    return args


def _accumulate_turns(line: str, usage: Usage):
    """Extract num_turns from a stream-json result line."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return
    if isinstance(obj, dict) and obj.get("type") == "result":
        usage.num_turns = max(usage.num_turns, obj.get("num_turns", 0))


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
