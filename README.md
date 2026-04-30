# release-flow

Automate the GitFlow release workflow across our repos.

## Install

```bash
pipx install release-flow
```

## First-time setup

```bash
release-flow init
```

You'll be asked for the GitLab base URL and your Personal Access Token (scope: `api`). The PAT is stored in plaintext in `~/.config/release-flow/config.toml` (Windows: `%APPDATA%\release-flow\config.toml`).

## Daily usage

In any repo (Java/Maven, Go, Helm-only) that follows GitFlow with `develop` and `master`:

```bash
release-flow              # auto-detect phase, run the flow
release-flow status       # diagnostic — show phase + state
release-flow doctor       # verify config and connectivity
release-flow abort        # cleanup current release branch
```

The first-run wizard configures:
- which file is the version source-of-truth per project type
- which secondary files keep the version in sync
- commit message templates
- MR title/body templates

## What it does

For each repo, the workflow goes:
1. **CLEAN** (on develop) → create release branch, strip `-SNAPSHOT`, commit "version freeze"
2. **FROZEN** → pull master, push release branch
3. **MR** → create MR `release/* → master` via GitLab API
4. **BUMP** (back on develop) → bump SNAPSHOT, commit "version bump"
5. **MERGE-BACK** → pull release branch, resolve version conflicts with `--ours`, push
6. **DONE**

The MR toward `master` waits for client approval and does NOT block the bump-back.

## Safety guarantees

`release-flow` will NEVER:
- delete `develop` or `master` (locally or remotely)
- force-push protected branches
- hard-reset protected branches

These are hard-coded invariants enforced at the lowest level (`git_repo.py`). No flag bypasses them.

## Project types

Built-in support for:
- **java** — `pom.xml` + `Chart.yaml` + `pipeline.yaml`
- **go** — Go const + `Chart.yaml` + `pipeline.yaml`
- **helm-only** — only `Chart.yaml` + `pipeline.yaml`

Add custom types by editing `~/.config/release-flow/config.toml`.

## Logs

Each run produces a JSONL audit log in `~/.local/state/release-flow/logs/<repo>/<timestamp>.jsonl`. Use `release-flow logs` to find them.
