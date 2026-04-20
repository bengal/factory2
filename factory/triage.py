"""Triage cascade-invalidated stories by checking spec diff relevance."""

import difflib
import subprocess
from pathlib import Path

from . import log
from .config import Config


_TRIAGE_PROMPT = """\
A specification file has been modified. You must determine whether a dependent \
story needs reprocessing.

## Changed specification: {changed_dep_id}

### Diff (unified format):
```
{spec_diff}
```

## Dependent story specification: {story_id}

{story_spec_content}

## Question

Does the change shown in the diff affect the implementation, tests, or \
verification of story {story_id}? Consider whether the change modifies any \
types, APIs, behaviors, test infrastructure, or conventions that story \
{story_id} depends on.

Answer YES or NO on the first line, followed by a one-sentence reason.\
"""


def compute_spec_diff(spec_id: str, config: Config) -> str | None:
    """Compute unified diff between the pre-update snapshot and the current spec.

    Returns the diff string, or None if there is no snapshot (first run).
    """
    current = config.specs_dir / f"{spec_id}.md"
    snapshot = config.state_dir / ".specs-prev" / f"{spec_id}.md"

    if not snapshot.exists():
        return None
    if not current.exists():
        return None

    old_lines = snapshot.read_text().splitlines(keepends=True)
    new_lines = current.read_text().splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"specs/{spec_id}.md (previous)",
        tofile=f"specs/{spec_id}.md (current)",
    ))

    return "".join(diff) if diff else ""


def should_reprocess(
    story_id: str,
    changed_dep_id: str,
    spec_diff: str,
    config: Config,
) -> tuple[bool, str]:
    """Ask Haiku whether a spec diff requires reprocessing a dependent story.

    Returns (should_reprocess, reason).
    Defaults to True on any failure (conservative).
    Logs the full model response to stories/{story_id}/log/triage.log.
    """
    story_spec = config.specs_dir / f"{story_id}.md"
    if not story_spec.exists():
        return True, "story spec not found"

    story_spec_content = story_spec.read_text()

    prompt = _TRIAGE_PROMPT.format(
        changed_dep_id=changed_dep_id,
        spec_diff=spec_diff,
        story_id=story_id,
        story_spec_content=story_spec_content,
    )

    log_dir = config.stories_dir / story_id / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "triage.log"

    try:
        result = subprocess.run(
            [
                config.cmd, "-p",
                "--output-format", "text",
                "--model", config.fast_model,
                "--max-turns", "1",
                "--allowedTools", "",
                "--dangerously-skip-permissions",
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=config.project_dir,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.warn(f"  Triage call failed for {story_id}: {e}")
        return True, f"triage call failed: {e}"

    # Write full response to log file (append for multiple deps)
    with open(log_file, "a") as f:
        f.write(f"=== Triage: {story_id} vs {changed_dep_id} ===\n")
        f.write(f"--- prompt ---\n{prompt}\n")
        f.write(f"--- response (exit {result.returncode}) ---\n")
        f.write(result.stdout or "(empty)")
        if result.stderr:
            f.write(f"\n--- stderr ---\n{result.stderr}")
        f.write("\n\n")

    if result.returncode != 0:
        log.warn(f"  Triage call failed for {story_id}: exit {result.returncode}")
        return True, f"triage call failed: exit {result.returncode}"

    output = result.stdout.strip()
    if not output:
        return True, "empty triage response"

    first_line = output.split("\n")[0].strip().upper()
    reason = output.split("\n")[1].strip() if "\n" in output else ""

    if first_line.startswith("NO"):
        return False, reason or "not relevant"
    return True, reason or "relevant"
