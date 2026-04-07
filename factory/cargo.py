"""Structured cargo command wrappers.

Parses cargo's JSON diagnostic output into clean, actionable summaries
instead of raw compiler output.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import log


@dataclass
class Diagnostic:
    level: str        # error, warning, note
    message: str
    file: str
    line: int | None
    rendered: str     # cargo's pre-formatted output

    def short(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.level}: {loc} — {self.message}"


@dataclass
class CargoResult:
    success: bool
    diagnostics: list[Diagnostic]
    error_count: int
    warning_count: int

    def summary(self) -> str:
        if self.success and not self.diagnostics:
            return "OK"
        parts = []
        if self.error_count:
            parts.append(f"{self.error_count} error(s)")
        if self.warning_count:
            parts.append(f"{self.warning_count} warning(s)")
        return ", ".join(parts) if parts else "OK"

    def format_errors(self, max_items: int = 10) -> str:
        """Format errors for logging or prompt injection."""
        errors = [d for d in self.diagnostics if d.level == "error"]
        lines = []
        for d in errors[:max_items]:
            lines.append(d.short())
        if len(errors) > max_items:
            lines.append(f"... and {len(errors) - max_items} more errors")
        return "\n".join(lines)


def check(project_dir: Path, tests: bool = False) -> CargoResult:
    """Run cargo check with JSON output, return structured result."""
    cmd = ["cargo", "check", "--message-format=json"]
    if tests:
        cmd.append("--tests")

    proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
    diagnostics = _parse_diagnostics(proc.stdout)

    return CargoResult(
        success=proc.returncode == 0,
        diagnostics=diagnostics,
        error_count=sum(1 for d in diagnostics if d.level == "error"),
        warning_count=sum(1 for d in diagnostics if d.level == "warning"),
    )


def test(project_dir: Path) -> CargoResult:
    """Run cargo test with JSON output, return structured result."""
    cmd = ["cargo", "test", "--message-format=json", "--", "--format=terse"]

    proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
    diagnostics = _parse_diagnostics(proc.stdout)

    return CargoResult(
        success=proc.returncode == 0,
        diagnostics=diagnostics,
        error_count=sum(1 for d in diagnostics if d.level == "error"),
        warning_count=sum(1 for d in diagnostics if d.level == "warning"),
    )


def clippy(project_dir: Path) -> CargoResult:
    """Run cargo clippy with JSON output, return structured result."""
    cmd = [
        "cargo", "clippy", "--message-format=json",
        "--", "-D", "warnings",
    ]

    proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
    diagnostics = _parse_diagnostics(proc.stdout)

    return CargoResult(
        success=proc.returncode == 0,
        diagnostics=diagnostics,
        error_count=sum(1 for d in diagnostics if d.level == "error"),
        warning_count=sum(1 for d in diagnostics if d.level == "warning"),
    )


def _parse_diagnostics(json_output: str) -> list[Diagnostic]:
    """Parse cargo's JSON output into Diagnostic objects."""
    diagnostics = []
    seen = set()  # deduplicate by message

    for line in json_output.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        if msg.get("reason") != "compiler-message":
            continue

        inner = msg.get("message", {})
        level = inner.get("level", "")
        message = inner.get("message", "")
        rendered = inner.get("rendered", "")

        if not message or level not in ("error", "warning"):
            continue

        # Deduplicate
        key = (level, message)
        if key in seen:
            continue
        seen.add(key)

        # Extract primary span location
        file_path = ""
        line_num = None
        spans = inner.get("spans", [])
        for span in spans:
            if span.get("is_primary"):
                file_path = span.get("file_name", "")
                line_num = span.get("line_start")
                break

        diagnostics.append(Diagnostic(
            level=level,
            message=message,
            file=file_path,
            line=line_num,
            rendered=rendered,
        ))

    return diagnostics
