"""Generate a codebase context snapshot to inject into prompts.

This saves Claude many turns of exploring with Glob/Read by providing
the module tree, public API signatures, and dependencies upfront.
"""

import re
from pathlib import Path

from .config import Config

# Patterns to extract public API signatures from Rust source
_SIGNATURE_PATTERNS = [
    re.compile(r"^\s*(pub(?:\(crate\))?\s+(?:async\s+)?fn\s+.+?)(?:\s*\{|$)"),
    re.compile(r"^\s*(pub(?:\(crate\))?\s+struct\s+\S+.*)"),
    re.compile(r"^\s*(pub(?:\(crate\))?\s+enum\s+\S+.*)"),
    re.compile(r"^\s*(pub(?:\(crate\))?\s+trait\s+\S+.*)"),
    re.compile(r"^\s*(pub(?:\(crate\))?\s+type\s+.+)"),
    re.compile(r"^\s*(pub(?:\(crate\))?\s+mod\s+\w+)"),
    re.compile(r"^\s*(pub(?:\(crate\))?\s+use\s+.+)"),
    re.compile(r"^\s*(impl(?:<[^>]*>)?\s+(?:\w+::)*\w+(?:<[^>]*>)?\s+(?:for\s+(?:\w+::)*\w+(?:<[^>]*>)?)?.*)"),
]


def generate_context(config: Config) -> str:
    """Generate a codebase context string for prompt injection."""
    project = config.project_dir

    if not (project / "Cargo.toml").exists():
        return ""

    sections = []

    # Module tree
    tree = _module_tree(project)
    if tree:
        sections.append(f"### Module Structure\n\n```\n{tree}```")

    # Public API per file
    api = _public_api(project)
    if api:
        sections.append(f"### Public API\n\n{api}")

    # Rust version constraint
    rust_ver = _rust_version(project)
    if rust_ver:
        sections.append(f"### Rust Version\n\nMinimum supported Rust version (MSRV): **{rust_ver}**. Do not add dependencies that require a newer rustc.")

    # Dependencies
    deps = _dependencies(project)
    if deps:
        sections.append(f"### Dependencies\n\n```toml\n{deps}```")

    if not sections:
        return ""

    return "## Codebase Context\n\n" + "\n\n".join(sections) + "\n"


def _find_source_roots(project: Path) -> list[tuple[str, Path]]:
    """Find all Rust source roots in a project.

    Returns a list of (label, src_path) tuples.  For a simple crate this
    is [("", project/src)].  For a Cargo workspace it returns one entry
    per member crate whose src/ directory exists, labelled by the member
    path (e.g. "crates/netfyr-state").
    """
    # Check for workspace members in Cargo.toml
    cargo_toml = project / "Cargo.toml"
    members = []
    if cargo_toml.exists():
        in_members = False
        try:
            for line in cargo_toml.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("members"):
                    in_members = True
                    continue
                if in_members:
                    if stripped == "]":
                        break
                    # Extract quoted path:  "crates/foo",
                    m = re.match(r'"([^"]+)"', stripped)
                    if m:
                        members.append(m.group(1))
        except OSError:
            pass

    if members:
        roots = []
        for member in members:
            src = project / member / "src"
            if src.is_dir():
                roots.append((member, src))
        if roots:
            return roots

    # Fallback: single-crate project
    src = project / "src"
    if src.is_dir():
        return [("", src)]

    return []


def _module_tree(project: Path) -> str:
    """Build a visual tree of Rust source files."""
    src_dirs = _find_source_roots(project)
    if not src_dirs:
        return ""

    lines = []
    for i, (label, src) in enumerate(src_dirs):
        if label:
            lines.append(f"{label}/")
        _tree_walk(src, "", lines, is_last=(i == len(src_dirs) - 1), is_root=(not label))
        if i < len(src_dirs) - 1:
            lines.append("")
    return "\n".join(lines)


def _tree_walk(path: Path, prefix: str, lines: list, is_last: bool, is_root: bool):
    if is_root:
        lines.append(f"{path.name}/")
        child_prefix = ""
    else:
        connector = "└── " if is_last else "├── "
        # Add a brief annotation for .rs files
        annotation = ""
        if path.suffix == ".rs":
            items = _extract_top_level_items(path)
            if items:
                annotation = f"  ({', '.join(items[:5])}{'...' if len(items) > 5 else ''})"
        lines.append(f"{prefix}{connector}{path.name}{annotation}")
        child_prefix = prefix + ("    " if is_last else "│   ")

    if path.is_dir():
        children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        # Filter to .rs files and directories only
        children = [c for c in children if c.is_dir() or c.suffix == ".rs"]
        for i, child in enumerate(children):
            _tree_walk(child, child_prefix, lines, i == len(children) - 1, False)


def _extract_top_level_items(path: Path) -> list[str]:
    """Extract short names of top-level public items from a Rust file."""
    items = []
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return items

    for line in text.splitlines():
        stripped = line.strip()
        # pub mod, pub struct, pub enum, pub trait, pub fn, pub type
        m = re.match(
            r"pub(?:\(crate\))?\s+(mod|struct|enum|trait|fn|type|async\s+fn)\s+(\w+)",
            stripped,
        )
        if m:
            kind = m.group(1).replace("async ", "")
            name = m.group(2)
            items.append(f"{kind} {name}")
    return items


def _public_api(project: Path) -> str:
    """Extract public API signatures from all Rust source files."""
    src_dirs = _find_source_roots(project)
    if not src_dirs:
        return ""

    sections = []
    for _label, src in src_dirs:
        for rs_file in sorted(src.rglob("*.rs")):
            sigs = _extract_signatures(rs_file)
            if sigs:
                rel = rs_file.relative_to(project)
                sig_text = "\n".join(f"  {s}" for s in sigs)
                sections.append(f"```rust\n// {rel}\n{sig_text}\n```")

    return "\n\n".join(sections)


def _extract_signatures(path: Path) -> list[str]:
    """Extract public function/type/trait signatures from a Rust file."""
    sigs = []
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return sigs

    in_test_module = False
    brace_depth = 0

    for line in text.splitlines():
        stripped = line.strip()

        # Track brace depth to skip test module contents
        if "#[cfg(test)]" in stripped:
            in_test_module = True
        if in_test_module:
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0 and in_test_module and brace_depth != 0:
                in_test_module = False
                brace_depth = 0
            continue

        for pattern in _SIGNATURE_PATTERNS:
            m = pattern.match(line)
            if m:
                sig = m.group(1).rstrip(" {,")
                # Clean up multi-line signatures
                sig = re.sub(r"\s+", " ", sig).strip()
                if sig and len(sig) < 200:  # skip absurdly long lines
                    sigs.append(sig)
                break

    return sigs


def _rust_version(project: Path) -> str:
    """Extract rust-version from workspace Cargo.toml."""
    cargo_toml = project / "Cargo.toml"
    if not cargo_toml.exists():
        return ""
    try:
        for line in cargo_toml.read_text().splitlines():
            if line.strip().startswith("rust-version"):
                # rust-version = "1.86"
                _, _, val = line.partition("=")
                return val.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _dependencies(project: Path) -> str:
    """Extract [dependencies] sections from Cargo.toml files."""
    parts = []

    # Root Cargo.toml
    root_deps = _extract_deps_from_toml(project / "Cargo.toml")
    if root_deps:
        parts.append(f"# (root)\n{root_deps}")

    # Workspace member Cargo.toml files
    for _label, src in _find_source_roots(project):
        member_toml = src.parent / "Cargo.toml"
        if member_toml.exists():
            deps = _extract_deps_from_toml(member_toml)
            if deps:
                rel = member_toml.relative_to(project)
                parts.append(f"# {rel}\n{deps}")

    return "\n\n".join(parts)


def _extract_deps_from_toml(cargo_toml: Path) -> str:
    """Extract [dependencies] section from a single Cargo.toml."""
    try:
        text = cargo_toml.read_text()
    except OSError:
        return ""

    lines = []
    in_deps = False
    for line in text.splitlines():
        if line.strip() == "[dependencies]":
            in_deps = True
            continue
        if in_deps:
            if line.startswith("["):
                break
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                lines.append(stripped)

    return "\n".join(lines) if lines else ""
