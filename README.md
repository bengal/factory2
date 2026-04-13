# factory2

An AI software factory that turns user stories into working Rust code. It reads specifications from a directory, analyzes dependencies between them, and processes each story through a multi-phase pipeline powered by Claude Code.

## How it works

```
specs/*.md ──► dependency analysis ──► per-story pipeline ──► working Rust project
                                            │
                                            ├─ understand (gap analysis)
                                            ├─ plan (implementation design)
                                            ├─ implement (write code)
                                            ├─ write-tests (from acceptance criteria)
                                            ├─ verify (run tests, fix, repeat)
                                            └─ commit (git commit with summary)
```

1. **Dependency analysis** — an LLM run reads all specs and produces a dependency graph (`deps.json`), determining which stories must be implemented first.

2. **Per-story pipeline** — each story passes through five phases, each a separate Claude Code invocation:

   | Phase | Input | Output | Purpose |
   |-------|-------|--------|---------|
   | understand | spec + codebase | `understand.md` | Gap analysis: what exists, what's missing |
   | plan | spec + understand.md | `plan.md` | Concrete implementation plan with file paths and signatures |
   | implement | spec + plan.md | Rust code | Write the code, ensure it compiles |
   | write-tests | spec + code | Test code | Tests derived from acceptance criteria |
   | verify | spec + code + tests | `results.md` | Run tests, fix failures, report results |
   | commit | results.md | git commit | Commit with message explaining what and why |

3. **Summary** — after all stories are processed, a final LLM run produces a combined summary of what was built.

### Failure handling

- If a story fails any phase, it is **quarantined** and all stories that depend on it are **skipped**.
- The verify phase retries up to N times (default 3) before quarantining.
- Other independent stories continue processing.

### Incremental runs

Run the factory again on the same workspace and it will:
- Skip stories that completed successfully and whose spec hasn't changed.
- Re-attempt quarantined and skipped stories (in case specs were fixed).
- Re-run dependency analysis only if any spec file changed.

To force reprocessing of specific stories (even if their spec hasn't changed):

```bash
python3 -m factory ./my-project --rerun 045-rpm-packaging
python3 -m factory ./my-project --rerun 045-rpm-packaging 048-readme
```

This resets their status and phases, then runs the normal pipeline. Stories that depend on a rerun story are automatically invalidated and reprocessed too.

### Cost tracking

Token usage (input and output) is tracked per story and per phase in `state.json`. The monitor displays totals with estimated cost.

## Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude`)
- Rust toolchain (`cargo`, `clippy`)

## Quick start

### 1. Create specs

Create a directory with one `.md` file per user story:

```
my-project/
└── specs/
    ├── auth.md
    ├── user-profile.md
    └── api-endpoints.md
```

Each spec should include acceptance criteria:

```markdown
# User Authentication

As a user, I want to log in with username and password so that I can
access protected resources.

## Acceptance Criteria

- POST /login accepts a JSON body with `username` and `password` fields
- Returns a JWT token on successful authentication
- Returns 401 with an error message on invalid credentials
- Passwords are verified against bcrypt hashes
- Tokens expire after 24 hours
```

### 2. Run the factory

```bash
# Anthropic API
export ANTHROPIC_API_KEY="sk-ant-..."
python3 -m factory ./my-project

# OR Vertex AI
export CLAUDE_CODE_USE_VERTEX=1
export CLOUD_ML_REGION=us-east5
export ANTHROPIC_VERTEX_PROJECT_ID=your-project-id
python3 -m factory ./my-project
```

### 3. Check results

```
my-project/
├── specs/                  # your input (unchanged)
├── state.json              # pipeline state + cost tracking
├── deps.md                 # dependency analysis (human-readable)
├── deps.json               # dependency graph (machine-readable)
├── stories/
│   └── auth/
│       ├── understand.md   # gap analysis
│       ├── plan.md         # implementation plan
│       ├── results.md      # test results
│       └── log/            # raw Claude output per phase
├── project/                # the generated Rust project (git repo)
│   ├── Cargo.toml
│   └── src/
└── output/
    └── summary.md          # combined summary of all stories
```

## Options

```
usage: factory [-h] [-j PARALLEL] [-r RETRIES] [-m MODEL]
               [--light-model LIGHT_MODEL] [--max-turns MAX_TURNS]
               [--verify-turns VERIFY_TURNS] [-v]
               workspace

  -j, --parallel N       Max parallel story pipelines (default: 1)
  -r, --retries N        Max verify fix attempts per story (default: 3)
  -m, --model MODEL      Model for implement/test/verify (default: claude-sonnet-4-6)
      --light-model MODEL  Model for understand/plan/deps (default: claude-sonnet-4-6)
      --max-turns N      Max turns per Claude run (default: 80)
      --verify-turns N   Max turns for verify phase (default: 120)
  -v, --verbose          Stream Claude output to terminal in real time
      --rerun STORY [STORY ...]  Force reprocessing of specific stories
  -h, --help             Show this help
```

Examples:

```bash
# Run with 4 parallel pipelines and opus for heavy phases
python3 -m factory -j 4 -m claude-opus-4-6 ./my-project

# More retries for verify, higher turn budget
python3 -m factory -r 5 --verify-turns 150 ./my-project

# Watch what Claude is doing in real time
python3 -m factory -v ./my-project
```

## Monitoring

While the factory is running, open a second terminal:

```bash
# Live dashboard — refreshes every 2s with per-story, per-phase status and costs
python3 -m factory.monitor ./my-project

# Tail logs for a specific story
python3 -m factory.monitor ./my-project tail auth

# One-shot status (for scripting)
python3 -m factory.monitor ./my-project once
```

The dashboard shows per-story token usage and estimated cost:
```
Factory Status  14:23:07
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total: 3  done:2  active:1  quarantined:0

  STORY                 STATUS         understand  plan        implement   write_tests verify         TOKENS
  ────────────────────────────────────────────────────────────────────────────────────────────────────────────
  auth                  done           done        done        done        done        done           45K/12K
  profile               in_progress    done        done        running     -           -              23K/8K
  api                   pending        -           -           -           -           -

  Total: 68K input, 20K output  (~$0.50 at Sonnet rates)
```

## Running in a container

For isolated execution (or when tests need root capabilities like network namespaces):

```bash
# Build and run
export ANTHROPIC_API_KEY="sk-ant-..."  # or set Vertex AI vars
./run_container.sh ./specs-dir -- -j 2

# Options
./run_container.sh \
  -o ./output-dir \        # workspace/output location (default: ./factory-output)
  -i my-image \            # image name (default: factory2)
  -b \                     # force rebuild image
  -R podman \              # runtime: docker or podman (default: auto-detect)
  ./specs-dir \
  -- -j 4 -m claude-opus-4-6   # factory options after --

# Stop a running factory
podman kill factory2-run    # or: docker kill factory2-run
```

The container runs with `--cap-add=NET_ADMIN --cap-add=SYS_ADMIN` instead of `--privileged`. A non-root user (`factory`) runs Claude Code, with passwordless `sudo` for commands that need root (e.g., network namespaces in tests).

### Vertex AI in containers

The container script auto-copies GCP credentials into the workspace:

```bash
export CLAUDE_CODE_USE_VERTEX=1
export CLOUD_ML_REGION=us-east5
export ANTHROPIC_VERTEX_PROJECT_ID=your-project-id

# Uses ~/.config/gcloud/application_default_credentials.json automatically.
# Or set GOOGLE_APPLICATION_CREDENTIALS to a service account key file.
./run_container.sh ./specs-dir
```

## Environment variables

| Variable | Purpose |
|----------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API authentication |
| `CLAUDE_CODE_USE_VERTEX` | Set to `1` to use Vertex AI |
| `CLOUD_ML_REGION` | Vertex AI region |
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project ID for Vertex AI |
| `CLAUDE_CMD` | Path to Claude CLI binary (default: `claude`) |
| `SKIP_PERMISSIONS` | Set to `0` to enable Claude tool permission prompts (default: `1`) |

## Project structure

```
factory2/
├── factory/                # Python package
│   ├── __main__.py         # CLI entry point (argparse)
│   ├── config.py           # Config dataclass
│   ├── log.py              # Colored logging
│   ├── state.py            # JSON state with file locking + cost tracking
│   ├── runner.py           # Claude CLI wrapper (streams output, parses usage)
│   ├── deps.py             # Dependency analysis + topological sort
│   ├── pipeline.py         # 5-phase per-story pipeline + git commit
│   ├── orchestrator.py     # Main loop (sequential + parallel)
│   └── monitor.py          # Live status dashboard
├── prompts/                # Prompt templates (plain markdown)
│   ├── analyze_deps.md
│   ├── understand.md
│   ├── plan.md
│   ├── implement.md
│   ├── write_tests.md
│   ├── verify.md
│   └── summarize.md
├── pyproject.toml          # Python project config (no external deps)
├── Containerfile           # Container image definition
├── entrypoint.sh           # Container entry point
└── run_container.sh        # Container launcher
```

## Customizing prompts

Edit the files in `prompts/` to adjust how Claude approaches each phase. The prompts are plain markdown — the orchestrator appends task-specific context (spec content, file paths, previous phase outputs) at the end before sending to Claude.

## Limitations

- Designed for Rust projects. Supporting other languages requires adjusting the prompts and the `cargo check` post-conditions in `factory/pipeline.py`.
- Parallel mode (`-j N > 1`) can produce merge conflicts if two stories modify the same file. Sequential mode is safer for tightly coupled stories.
- The LLM-based dependency analysis can miss implicit dependencies. Consider adding explicit `depends_on` declarations in your spec frontmatter for critical ordering.
