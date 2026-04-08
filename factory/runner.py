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
    activity_file: Path | None = None,
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
                if activity_file:
                    _update_activity(stripped, activity_file)

        proc.wait()

    if activity_file:
        activity_file.unlink(missing_ok=True)

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


def _update_activity(line: str, activity_file: Path):
    """Parse a stream-json line and write current activity to file."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return

    activity = _extract_activity(obj)
    if activity:
        tmp = activity_file.with_suffix(".tmp")
        tmp.write_text(activity)
        tmp.rename(activity_file)


def _extract_activity(obj) -> str | None:
    """Extract a human-readable activity string from a stream-json object."""
    if not isinstance(obj, dict):
        return None

    # Tool results
    if obj.get("type") == "tool_result":
        return None

    # Final result
    if obj.get("type") == "result":
        return "Done" if obj.get("subtype") == "success" else "Failed"

    # Assistant messages with content
    msg = obj.get("message") if obj.get("type") == "assistant" else None
    if not msg:
        return None

    content = msg.get("content", [])
    if not isinstance(content, list):
        return None

    for block in reversed(content):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")

        if btype == "tool_use":
            name = block.get("name", "")
            inp = block.get("input", {})
            return _format_tool_activity(name, inp)

        if btype == "thinking":
            return "Thinking..."

        if btype == "text":
            text = block.get("text", "").strip()
            if text:
                # First line, truncated
                first_line = text.split("\n")[0]
                if len(first_line) > 80:
                    return first_line[:77] + "..."
                return first_line

    return None


def _format_tool_activity(name: str, inp: dict) -> str:
    """Format a tool use into a short activity string."""
    # Normalize qwen tool names
    display = {
        "read_file": "Read", "write_file": "Write", "edit": "Edit",
        "glob": "Glob", "grep_search": "Grep",
        "run_shell_command": "Bash",
    }.get(name, name)

    if display in ("Read", "Write", "Edit"):
        path = inp.get("file_path", inp.get("path", ""))
        if path:
            # Show just the filename or last 2 path components
            parts = path.rsplit("/", 2)
            short = "/".join(parts[-2:]) if len(parts) > 1 else path
            return f"{display} {short}"
        return display

    if display == "Bash":
        cmd = inp.get("command", "")
        if cmd:
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            return f"$ {cmd}"
        return "Bash"

    if display == "Grep":
        pattern = inp.get("pattern", "")
        return f"Grep {pattern[:40]}" if pattern else "Grep"

    if display == "Glob":
        pattern = inp.get("pattern", "")
        return f"Glob {pattern[:40]}" if pattern else "Glob"

    return display


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
