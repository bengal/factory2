from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    workspace: Path
    factory_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    max_parallel: int = 1
    max_retries: int = 3
    strong_model: str = "claude-sonnet-4-6"   # plan, implement
    default_model: str = "claude-sonnet-4-6"  # understand, write-tests, verify
    fast_model: str = "claude-sonnet-4-6"     # analyze-deps, summarize
    max_turns: int = 80
    verify_turns: int = 120
    verbose: bool = False
    claude_cmd: str = "claude"
    skip_permissions: bool = True

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
