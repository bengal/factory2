from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    workspace: Path
    factory_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    max_parallel: int = 1
    max_retries: int = 3
    strong_model: str = "claude-opus-4-6"     # plan
    default_model: str = "claude-sonnet-4-6"  # understand, implement, write-tests, verify
    fast_model: str = "claude-haiku-4-5"  # analyze-deps, summarize, commit
    max_turns: int = 100
    verify_turns: int = 120
    verbose: bool = False
    backend: str = "claude"    # "claude" or "qwen"
    cmd: str = "claude"        # CLI binary name/path
    skip_permissions: bool = True
    rerun: list[str] = field(default_factory=list)
    llm_deps: bool = False
    git_author_name: str = "Factory"
    git_author_email: str = "factory@localhost"

    @property
    def specs_dir(self) -> Path:
        return self.workspace / "specs"

    @property
    def project_dir(self) -> Path:
        return self.workspace / "project"

    @property
    def stories_dir(self) -> Path:
        return self.workspace / "stories"

    @property
    def output_dir(self) -> Path:
        return self.workspace / "output"

    @property
    def prompts_dir(self) -> Path:
        return self.factory_dir / "prompts"

    @property
    def state_file(self) -> Path:
        return self.workspace / "state.json"

    @property
    def deps_file(self) -> Path:
        return self.workspace / "deps.json"
