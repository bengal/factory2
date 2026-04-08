"""Live monitoring dashboard for the factory pipeline.

Usage:
    python -m factory.monitor <workspace>              # live dashboard
    python -m factory.monitor <workspace> tail          # tail all active logs
    python -m factory.monitor <workspace> tail story-id # tail one story's logs
    python -m factory.monitor <workspace> once          # single status snapshot
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ── Colors ───────────────────────────────────────────────────────

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
DIM = "\033[2m"
NC = "\033[0m"

STATUS_COLORS = {
    "done": GREEN,
    "in_progress": BLUE,
    "running": BLUE,
    "pending": DIM,
    "quarantined": RED,
    "failed": RED,
    "skipped": YELLOW,
    "-": DIM,
}


def colored_status(s: str) -> str:
    color = STATUS_COLORS.get(s, "")
    return f"{color}{s}{NC}"


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


# Per-million-token pricing (input, cache_write, cache_read, output)
_MODEL_RATES = {
    "opus": (15, 18.75, 1.50, 75),
    "sonnet": (3, 3.75, 0.30, 15),
    "haiku": (0.80, 1.00, 0.08, 4),
    "qwen": (0, 0, 0, 0),  # free tier (oauth) or negligible cost
}


def _model_tier(model: str) -> str:
    """Map a model ID like 'claude-opus-4-6' or 'qwen3-coder-plus' to a tier name."""
    m = model.lower()
    if "qwen" in m or m == "coder-model":
        return "qwen"
    for tier in ("opus", "sonnet", "haiku"):
        if tier in m:
            return tier
    return "sonnet"  # default fallback


def _estimate_cost(cost_entry: dict) -> float:
    tier = _model_tier(cost_entry.get("model", ""))
    inp_rate, cache_w_rate, cache_r_rate, out_rate = _MODEL_RATES[tier]
    inp = cost_entry.get("input_tokens", 0)
    out = cost_entry.get("output_tokens", 0)
    cache_w = cost_entry.get("cache_creation_tokens", 0)
    cache_r = cost_entry.get("cache_read_tokens", 0)
    return (
        inp / 1_000_000 * inp_rate
        + cache_w / 1_000_000 * cache_w_rate
        + cache_r / 1_000_000 * cache_r_rate
        + out / 1_000_000 * out_rate
    )


# ── Status display ───────────────────────────────────────────────


def show_status(workspace: Path):
    state_file = workspace / "state.json"
    if not state_file.exists():
        print("Waiting for factory to start (no state.json yet)...")
        return

    data = json.loads(state_file.read_text())
    stories = data.get("stories", {})

    # Summary counts
    counts = {}
    for s in stories.values():
        st = s.get("status", "pending")
        counts[st] = counts.get(st, 0) + 1

    total = len(stories)
    print(f"{BOLD}Factory Status{NC}  {time.strftime('%H:%M:%S')}")
    print(f"{DIM}{'━' * 70}{NC}")

    parts = [f"Total: {BOLD}{total}{NC}"]
    for label, color in [("done", GREEN), ("in_progress", BLUE), ("pending", DIM),
                          ("skipped", YELLOW), ("quarantined", RED)]:
        if counts.get(label, 0):
            parts.append(f"{color}{label}:{counts[label]}{NC}")
    print("  " + "  ".join(parts))
    print()

    # Per-story table
    stories_dir = workspace / "stories"
    phases = ["understand", "plan", "implement", "write_tests", "verify"]

    # Dynamic column width based on longest story ID, capped at 40
    name_width = min(max((len(sid) for sid in stories), default=20) + 2, 40)

    # Header
    header = f"  {BOLD}{'STORY':<{name_width}}{'STATUS':<15}"
    for p in phases:
        header += f"{p:<13}"
    header += f"{'TOKENS':>12}  {'REQS':>5}{NC}"
    print(header)
    print(f"  {DIM}{'─' * (name_width + 15 + 13 * len(phases) + 12 + 7)}{NC}")

    for sid in sorted(stories.keys()):
        s = stories[sid]
        status = s.get("status", "pending")

        # ANSI codes add 11 chars to colored_status output, so pad accordingly
        line = f"  {sid:<{name_width}}{colored_status(status):<{15 + 11}}"

        for p in phases:
            ps = s.get("phases", {}).get(p, {}).get("status", "-")
            line += f"{colored_status(ps):<{13 + 11}}"

        # Tokens (input = uncached + cache_write + cache_read)
        costs = s.get("costs", {})
        total_in = sum(
            c.get("input_tokens", 0) + c.get("cache_creation_tokens", 0) + c.get("cache_read_tokens", 0)
            for c in costs.values()
        )
        total_out = sum(c.get("output_tokens", 0) for c in costs.values())
        story_turns = sum(c.get("num_turns", 0) for c in costs.values())
        if total_in or total_out:
            line += f"{format_tokens(total_in)}/{format_tokens(total_out):>6}"
        else:
            line += f"{'':>12}"
        if story_turns:
            line += f"  {story_turns:>5}"

        print(line)

        # Show reason if quarantined/skipped, or activity if in progress
        if status == "quarantined":
            reason = s.get("quarantine_reason", "")
            if reason:
                print(f"  {DIM}  └─ {reason}{NC}")
        elif status == "skipped":
            reason = s.get("skip_reason", "")
            if reason:
                print(f"  {DIM}  └─ {reason}{NC}")
        elif status == "in_progress":
            activity_file = stories_dir / sid / "activity"
            if activity_file.exists():
                try:
                    activity = activity_file.read_text().strip()
                    if activity:
                        # Find current phase
                        cur_phase = ""
                        for p in phases:
                            ps = s.get("phases", {}).get(p, {}).get("status", "")
                            if ps == "running":
                                cur_phase = p
                                break
                        prefix = f"{cur_phase}: " if cur_phase else ""
                        if len(prefix + activity) > 80:
                            activity = activity[:80 - len(prefix)] + "..."
                        print(f"  {DIM}  └─ {prefix}{activity}{NC}")
                except OSError:
                    pass

    # Total costs
    print()
    all_costs = data.get("stories", {})
    grand_in = grand_cache_w = grand_cache_r = grand_out = 0
    grand_turns = 0
    total_est = 0.0
    for s in all_costs.values():
        for c in s.get("costs", {}).values():
            grand_in += c.get("input_tokens", 0)
            grand_cache_w += c.get("cache_creation_tokens", 0)
            grand_cache_r += c.get("cache_read_tokens", 0)
            grand_out += c.get("output_tokens", 0)
            grand_turns += c.get("num_turns", 0)
            total_est += _estimate_cost(c)

    grand_all_in = grand_in + grand_cache_w + grand_cache_r
    if grand_all_in or grand_out:
        cost_or_turns = f"{DIM}(~${total_est:.2f}){NC}" if total_est else ""
        if grand_turns:
            cost_or_turns = f"{BOLD}{grand_turns}{NC} requests  " + cost_or_turns
        print(
            f"  {BOLD}Total:{NC} {format_tokens(grand_all_in)} input "
            f"{DIM}({format_tokens(grand_cache_w)} write, {format_tokens(grand_cache_r)} read){NC}, "
            f"{format_tokens(grand_out)} output  "
            + cost_or_turns
        )

    # Active log files
    if stories_dir.exists():
        active = []
        for logf in sorted(stories_dir.rglob("*.log")):
            try:
                age = time.time() - logf.stat().st_mtime
                if age < 120:  # modified in last 2 minutes
                    size = logf.stat().st_size
                    rel = logf.relative_to(workspace)
                    active.append((rel, size))
            except OSError:
                pass

        if active:
            print(f"\n  {BOLD}Active logs:{NC}")
            for rel, size in active:
                print(f"    {CYAN}{rel}{NC} ({format_tokens(size)}B)")


def dashboard_loop(workspace: Path):
    try:
        while True:
            os.system("clear")
            show_status(workspace)
            print(f"\n{DIM}Refreshing every 2s. Ctrl+C to stop.{NC}")
            time.sleep(2)
    except KeyboardInterrupt:
        pass


# ── Tail logs ────────────────────────────────────────────────────


def tail_logs(workspace: Path, story_filter: str = ""):
    stories_dir = workspace / "stories"
    target = stories_dir / story_filter if story_filter else stories_dir

    if not target.exists():
        print(f"No directory found at {target}")
        if stories_dir.exists():
            print("Available stories:")
            for d in sorted(stories_dir.iterdir()):
                if d.is_dir():
                    print(f"  {d.name}")
        sys.exit(1)

    print(f"{BOLD}Tailing logs in: {target}{NC}")
    print(f"{DIM}Ctrl+C to stop{NC}\n")

    # Find existing log files
    logs = sorted(target.rglob("*.log"))
    if not logs:
        print("No log files found yet. Waiting...")
        while not logs:
            time.sleep(1)
            logs = sorted(target.rglob("*.log"))

    try:
        subprocess.run(
            ["tail", "-F"] + [str(l) for l in logs],
            cwd=workspace,
        )
    except KeyboardInterrupt:
        pass


# ── Main ─────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Factory pipeline monitor")
    parser.add_argument("workspace", type=Path, help="Workspace directory")
    parser.add_argument(
        "action", nargs="?", default="status",
        choices=["status", "tail", "once"],
        help="status (live dashboard), tail (follow logs), once (single snapshot)",
    )
    parser.add_argument("story_filter", nargs="?", default="", help="Filter to a specific story")

    args = parser.parse_args()
    workspace = args.workspace.resolve()

    if args.action == "status":
        dashboard_loop(workspace)
    elif args.action == "tail":
        tail_logs(workspace, args.story_filter)
    elif args.action == "once":
        show_status(workspace)


if __name__ == "__main__":
    main()
