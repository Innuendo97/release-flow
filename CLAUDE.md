# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`release-flow` is a Python 3.11+ CLI (entry point `release-flow = release_flow.cli:main`, packaged via `pipx`) that automates the GitFlow release workflow across multi-language repos (Java/Maven, Go, Helm-only). It drives a state machine over a git repo + GitLab MR creation, with built-in recovery for anomalous repo states.

User-facing prompts and printed messages are in **Italian** by design — preserve that tone when modifying user-facing strings.

## Common commands

```powershell
# Install dev environment (editable + dev deps)
pip install -e ".[dev]"

# Lint + type-check (CI gates)
ruff check src tests
mypy src                          # mypy is strict mode (see mypy.ini)

# Test suites
pytest tests/unit                                  # unit only (cross-platform)
pytest tests/integration -m "not invariant"        # integration (real git subprocess)
pytest -m invariant                                # safety invariants — must NEVER fail
pytest tests/                                      # full suite
pytest tests/unit/test_flow.py::test_name -v       # single test
pytest --cov=release_flow --cov-report=term --cov-fail-under=75   # coverage gate

# Build distributable wheel
python -m build
```

CI (`.github/workflows/ci.yml`) runs lint → unit (matrix py3.11/3.12/3.13 × ubuntu/windows) → integration (ubuntu+windows) → invariants → coverage (75% gate, full suite) → package smoke test. The `invariants` job is the merge gate — protected-branch tests must always pass.

## Architecture

### State machine (the core abstraction)

The flow is an **8-state machine** (`states.Phase`): `CLEAN → RELEASE_BRANCH_CREATED → FROZEN_LOCAL → FROZEN_PUSHED → MR_MASTER_OPEN → BUMP_PENDING → BUMPED_LOCAL → DONE`.

Phase detection is a **pure function** (`states.detect_phase`) over a `RepoSnapshot` — a frozen dataclass capturing branch, working tree state, version, MRs, and ancestor relationships. `states.build_snapshot` is the only place that does git/GitLab I/O to construct one. Keep `detect_phase` pure: any new logic that needs I/O belongs in `build_snapshot`.

Important detection rule: "frozen" is detected from the **version** (non-SNAPSHOT on a release branch), not from the commit message — this is robust to merges from master that supersede the original "version freeze" commit.

### Orchestrator loop (`flow.run`)

`flow.run` is the top-level loop (capped at 20 iterations). Each iteration:

1. Build snapshot → run pre-flight (`run_preflight`) + recovery detection (`recovery.detect_recovery_needed`).
2. If recovery needed (Caso A/B/E), dispatch via `_handle_recovery` and re-snapshot.
3. Apply `evaluate_branch_policy` if not on develop/release branch.
4. Detect phase → dispatch to the matching `execute_phase_*` function → loop.

Each `execute_phase_*` is a discrete unit — adding a new phase means: enum value in `Phase`, branch in `detect_phase`, `execute_phase_X` function, and dispatch arm in `flow.run`.

### Recovery sub-flows

`recovery.py` implements Casi A/B/E with a **decide/apply split**: `recover_caso_X` returns a plan (pure, no I/O — testable), `apply_caso_X_plan` executes via `GitRepo`. When adding new recovery cases, keep this split.

### Protected-branch invariant (load-bearing)

`git_repo.py` defines `PROTECTED_BRANCH_NAMES = frozenset({"develop", "master", "main"})`. The internal helper `_refuse_if_protected` is called by `delete_local_branch`, `delete_remote_branch`, `force_push`, `hard_reset_to`. **This is a hard-coded invariant — there is no flag, config, or argument that bypasses it.** Tests under `pytest -m invariant` enforce this and gate CI merges. Never weaken these checks.

`GitRepo` is the **only** module that runs git subprocess commands in production. Don't shell out to git from elsewhere.

### Pure-vs-impure separation

The codebase deliberately separates pure modules (no I/O, no network) from I/O modules:

- **Pure**: `states` (snapshot → phase), `version_bump` (semver parsing/bumping), `project_detector`, plan-construction halves of `recovery`.
- **I/O**: `git_repo`, `gitlab_client`, `version_io` (file read/write), `prompts`, `logging_setup`, `cli`, the `apply_*` halves of `recovery`, `flow.run`.

Tests rely on this split — keep new logic on the pure side wherever possible.

### Version handling quirks

`version_bump` recognizes both `-SNAPSHOT` (Maven standard) and `+SNAPSHOT` (some `pipeline.yaml` files) as equivalent for comparison. On write (`version_io.write_version_in_file`), the file's original separator is preserved. Don't normalize separators on write.

`pom.xml` parsing strips `<parent>...</parent>` first to avoid grabbing `parent.version` instead of the project's own `<version>`.

### Config

`config.py` loads `~/.config/release-flow/config.toml` (or `%APPDATA%\release-flow\config.toml` on Windows). Layered precedence: file < env (`GITLAB_TOKEN`) < CLI flags. The default config template is embedded as `_DEFAULT_CONFIG_TEMPLATE` in `cli.py` and written by `release-flow init`.

`ProjectTypeConfig.detect` markers support negation (`"!pom.xml"` = must NOT exist) — `project_detector` iterates project types in dict insertion order, first full match wins.

### Audit logging

Each run writes a JSONL file at `<log_dir>/<repo_name>/<UTC-timestamp>.jsonl`. `AuditLogger` is created in `cli._cmd_main` and threaded into `flow.run` as an optional argument — passing `None` is supported (used by tests).

## Conventions

- **Italian** for user-facing prompts/output; English for code, comments, errors raised programmatically.
- All custom exceptions inherit from `ReleaseFlowError` (see `exceptions.py`). `UserAbortError` is caught at the CLI boundary and prints a friendly message instead of a traceback.
- Frozen dataclasses for value objects (`RepoSnapshot`, `PreflightResult`, `BranchPolicyResult`, `FlowResult`, `RecoveryPlan`, `MergeRequest`, `GitResult`, etc.).
- mypy `strict = True` — new code must type-check cleanly; don't add `# type: ignore` without a comment justifying it.
- Ruff selects `E,F,I,N,UP,B,SIM,RUF`; `E501` is off (formatter handles line length, configured to 100).
- pytest markers: `invariant` (safety, never fail) and `integration` (real git). Use `--strict-markers`; declare new markers in `pyproject.toml`.
