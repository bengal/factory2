import json
from graphlib import TopologicalSorter, CycleError
from pathlib import Path

from . import log
from .config import Config
from .runner import run_claude
from .state import State, specs_combined_hash


def run_dependency_analysis(config: Config, story_ids: list[str], state: State):
    """Run LLM to produce deps.json, or skip if specs unchanged."""
    deps_file = config.deps_file
    hash_file = config.workspace / ".specs_hash"

    # Incremental: skip if specs haven't changed
    if deps_file.exists() and hash_file.exists():
        old_hash = hash_file.read_text().strip()
        new_hash = specs_combined_hash(config.specs_dir)
        if old_hash == new_hash:
            log.info("Dependencies unchanged, skipping analysis")
            return

    log.phase(f"Analyzing dependencies across {len(story_ids)} stories...")

    prompt_template = (config.prompts_dir / "analyze_deps.md").read_text()

    specs_section = ""
    for spec_file in sorted(config.specs_dir.glob("*.md")):
        sid = spec_file.stem
        specs_section += f"\n### {sid}\n\n{spec_file.read_text()}\n\n---\n"

    prompt = (
        f"{prompt_template}\n\n"
        f"## Specifications\n{specs_section}\n\n"
        f"Write the dependency files to:\n"
        f"- {config.workspace}/deps.md (human-readable analysis)\n"
        f"- {deps_file} (machine-readable, format specified above)\n"
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    log_file = config.output_dir / "deps_analysis.log"

    success, usage = run_claude(
        prompt=prompt,
        log_file=log_file,
        model=config.fast_model,
        max_turns=config.max_turns,
        workdir=config.workspace,
        claude_cmd=config.claude_cmd,
        skip_permissions=config.skip_permissions,
        verbose=config.verbose,
    )

    if not success:
        log.warn("Dependency analysis Claude run failed")

    if not deps_file.exists():
        log.warn("deps.json not produced, creating fallback with no dependencies")
        _create_fallback_deps(deps_file, story_ids)
    else:
        try:
            data = json.loads(deps_file.read_text())
            assert "stories" in data and "dependencies" in data
        except (json.JSONDecodeError, AssertionError):
            log.warn("deps.json has invalid structure, creating fallback")
            _create_fallback_deps(deps_file, story_ids)

    hash_file.write_text(specs_combined_hash(config.specs_dir))


def _create_fallback_deps(deps_file: Path, story_ids: list[str]):
    data = {
        "stories": story_ids,
        "dependencies": {sid: [] for sid in story_ids},
    }
    deps_file.write_text(json.dumps(data, indent=2))


def topo_sort(deps_file: Path) -> list[str]:
    """Return story IDs in dependency order (dependencies first)."""
    data = json.loads(deps_file.read_text())
    stories = data["stories"]
    dependencies = data["dependencies"]

    graph = {s: set(dependencies.get(s, [])) for s in stories}

    sorter = TopologicalSorter(graph)
    try:
        return list(sorter.static_order())
    except CycleError as e:
        log.warn(f"Cycle detected in dependencies: {e}")
        return stories


def get_dependencies(story_id: str, deps_file: Path) -> list[str]:
    data = json.loads(deps_file.read_text())
    return data.get("dependencies", {}).get(story_id, [])


def get_dependents(story_id: str, deps_file: Path) -> list[str]:
    data = json.loads(deps_file.read_text())
    return [
        sid
        for sid, deps in data.get("dependencies", {}).items()
        if story_id in deps
    ]
