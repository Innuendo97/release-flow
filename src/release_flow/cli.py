"""CLI entry point: argparse + subcommand dispatch."""

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from release_flow import __version__

if TYPE_CHECKING:
    from release_flow.prompts import QuestionaryPrompter


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    p = argparse.ArgumentParser(
        prog="release-flow",
        description="Automate GitFlow release workflow across multi-language repos",
    )
    p.add_argument("--version", action="version", version=f"release-flow {__version__}")
    # Global flags
    p.add_argument("--config", type=Path, help="Override config file path")
    p.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    p.add_argument("-y", "--no-confirm", action="store_true", help="Skip confirmations")
    # Main-command flags
    p.add_argument("--release-version", help="Override release version")
    p.add_argument("--next-version", help="Override next SNAPSHOT version")
    p.add_argument("--bump", choices=["patch", "minor", "major"], help="Bump strategy")
    p.add_argument("--mr-master-body-file", type=Path, help="Read MR body from file")
    p.add_argument("--allow-dirty", action="store_true", help="Allow dirty working tree")
    p.add_argument("--restart-from", help="Force phase to restart from")
    p.add_argument("--from-branch", help="Override starting branch")
    # Subcommands
    sub = p.add_subparsers(dest="command")
    sub.add_parser("status", help="Show current phase and repo state")
    sub.add_parser("init", help="Initial setup wizard")
    sub.add_parser("doctor", help="Verify config and connectivity")
    sub.add_parser("abort", help="Cleanup current release branch")
    sub.add_parser("config-edit", help="Open config file in editor")
    sub.add_parser("logs", help="Show audit log location")
    return p


def main(argv: list[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    cmd = args.command or "main"
    try:
        if cmd == "main":
            return _cmd_main(args)
        if cmd == "status":
            return _cmd_status(args)
        if cmd == "init":
            return _cmd_init(args)
        if cmd == "doctor":
            return _cmd_doctor(args)
        if cmd == "abort":
            return _cmd_abort(args)
        if cmd == "config-edit":
            return _cmd_config_edit(args)
        if cmd == "logs":
            return _cmd_logs(args)
        parser.error(f"unknown command: {cmd}")
        return 2
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130


def _cmd_main(args: argparse.Namespace) -> int:
    """Run the release flow from current state."""
    from release_flow.config import default_config_path, load_config
    from release_flow.flow import run as flow_run
    from release_flow.gitlab_client import GitLabClient
    from release_flow.prompts import QuestionaryPrompter

    cfg_path = args.config or default_config_path()
    cfg = load_config(cfg_path)
    gitlab = GitLabClient(
        base_url=cfg.gitlab.base_url,
        token=cfg.gitlab.token,
        timeout=cfg.gitlab.http_timeout_seconds,
    )
    prompter = QuestionaryPrompter()
    result = flow_run(
        repo_root=Path.cwd(),
        config=cfg,
        gitlab=gitlab,
        prompter=prompter,
        allow_dirty=args.allow_dirty,
    )
    print(f"\n--- {result.final_phase.value} ---")
    if result.created_mr:
        print(f"MR creata: {result.created_mr.web_url}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    """Show current phase and repo state."""
    from release_flow.config import default_config_path, load_config
    from release_flow.flow import _build_filespecs
    from release_flow.git_repo import GitRepo
    from release_flow.gitlab_client import GitLabClient
    from release_flow.project_detector import detect_project_type
    from release_flow.states import build_snapshot, detect_phase

    cfg_path = args.config or default_config_path()
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        print(f"Errore caricamento config: {e}")
        return 1

    repo = Path.cwd()
    git = GitRepo(repo)
    if not git.is_git_repo():
        print(f"{repo} non è un repo git")
        return 1

    try:
        project_type_name = detect_project_type(
            repo, {n: {"detect": pt.detect} for n, pt in cfg.project_types.items()}
        )
    except Exception as e:
        print(f"Errore rilevamento tipo progetto: {e}")
        return 1
    project_type = cfg.project_types[project_type_name]
    primary, secondaries = _build_filespecs(repo, project_type)

    gitlab = GitLabClient(
        base_url=cfg.gitlab.base_url, token=cfg.gitlab.token,
    )

    # Find any release branches and try to fetch their MRs
    mrs = []
    try:
        project_path = gitlab.project_path_from_url(git.remote_url("origin"))
        for b in git.local_branches() + [
            x.replace("origin/", "", 1) for x in git.remote_branches()
        ]:
            if b.startswith(cfg.defaults.release_branch_prefix):
                mrs.extend(gitlab.list_open_mrs(project_path, source_branch=b))
    except Exception as e:
        print(f"Avviso: impossibile contattare GitLab ({e}); proseguo senza MR info.")

    snapshot = build_snapshot(
        git=git, primary=primary, secondaries=secondaries,
        release_branch_prefix=cfg.defaults.release_branch_prefix,
        mrs_for_release_branch=mrs,
    )
    try:
        phase = detect_phase(snapshot)
    except Exception as e:
        print(f"Errore rilevamento fase: {e}")
        return 1

    print(f"Repo:          {repo.name}")
    print(f"Tipo:          {project_type_name}")
    print(f"Branch:        {snapshot.current_branch}")
    print(f"Working tree:  {'pulito' if snapshot.working_tree_clean else 'sporco'}")
    print(f"Versione:      {snapshot.primary_version}")
    print(f"Fase:          {phase.value}")
    if mrs:
        for mr in mrs:
            print(f"MR aperte:     !{mr.iid} {mr.title} -> {mr.target_branch}")
    return 0


def _init_prompter() -> "QuestionaryPrompter":
    """Factory — separated so tests can monkeypatch it."""
    from release_flow.prompts import QuestionaryPrompter

    return QuestionaryPrompter()


def _cmd_init(args: argparse.Namespace) -> int:
    """Wizard di setup iniziale: chiede gitlab URL/PAT e scrive config."""
    import gitlab

    from release_flow.config import default_config_path

    cfg_path = args.config or default_config_path()
    if cfg_path.exists():
        print(f"Config già esistente in {cfg_path}. Modifica con 'release-flow config-edit'.")
        return 0

    prompter = _init_prompter()
    base_url = prompter.ask("GitLab URL", default="https://gitlab.alm.poste.it")
    token = prompter.ask("GitLab Personal Access Token", default="")
    if not token:
        print("Token richiesto.")
        return 1

    # Validate token by hitting /user
    try:
        gl = gitlab.Gitlab(url=base_url, private_token=token, timeout=10)
        gl.auth()
        user = gl.user
        if user:
            print(f"Token valido (utente: {user.username})")
        else:
            print("Token valido")
    except Exception as e:
        print(f"Token non valido o GitLab non raggiungibile: {e}")
        return 1

    default_bump = prompter.ask("Default bump strategy", default="patch")

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        _DEFAULT_CONFIG_TEMPLATE.format(
            base_url=base_url,
            token=token,
            default_bump=default_bump,
        ),
        encoding="utf-8",
    )
    print(f"\nConfig scritta in {cfg_path}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Verify config and connectivity."""
    import gitlab

    from release_flow.config import default_config_path, load_config

    cfg_path = args.config or default_config_path()
    try:
        cfg = load_config(cfg_path)
        print(f"Config caricata: {cfg_path}")
    except Exception as e:
        print(f"Config: {e}")
        return 1

    try:
        gl = gitlab.Gitlab(url=cfg.gitlab.base_url, private_token=cfg.gitlab.token, timeout=10)
        gl.auth()
        user = gl.user.username if gl.user else "unknown"
        print(f"GitLab raggiungibile, utente: {user}")
    except Exception as e:
        print(f"GitLab: {e}")
        return 1

    print(f"Tipi progetto configurati: {list(cfg.project_types.keys())}")
    return 0


def _cmd_abort(args: argparse.Namespace) -> int:
    """Cleanup current release branch."""
    from release_flow.config import default_config_path, load_config
    from release_flow.git_repo import GitRepo
    from release_flow.prompts import QuestionaryPrompter

    cfg_path = args.config or default_config_path()
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        print(f"Errore caricamento config: {e}")
        return 1
    repo = Path.cwd()
    git = GitRepo(repo)
    if not git.is_git_repo():
        print(f"{repo} non è un repo git")
        return 1
    branch = git.current_branch()
    if not branch.startswith(cfg.defaults.release_branch_prefix):
        print(f"Non sei su un release branch (sei su {branch}). Niente da abortire.")
        return 0

    prompter = QuestionaryPrompter()
    print(f"Sto per cancellare {branch} (locale e remoto).")
    if not prompter.confirm("Confermi cancellazione locale?", default=False):
        return 0
    if not prompter.confirm("Confermi cancellazione su origin?", default=False):
        return 0
    typed = prompter.ask(f"Per sicurezza, digita esattamente '{branch}'", default="")
    if typed != branch:
        print("Conferma fallita. Annullo.")
        return 1

    git.checkout(cfg.defaults.develop_branch)
    git.delete_local_branch(branch)
    git.delete_remote_branch("origin", branch)
    print(f"{branch} cancellato.")
    return 0


def _cmd_config_edit(args: argparse.Namespace) -> int:
    """Open config file in editor."""
    import os
    import subprocess

    from release_flow.config import default_config_path

    cfg_path = args.config or default_config_path()
    if not cfg_path.exists():
        print(f"Config non esiste in {cfg_path}. Lancia 'release-flow init'.")
        return 1
    editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vi")
    subprocess.run([editor, str(cfg_path)])
    return 0


def _cmd_logs(args: argparse.Namespace) -> int:
    """Show audit log location."""
    from release_flow.config import default_config_path, load_config

    cfg_path = args.config or default_config_path()
    try:
        cfg = load_config(cfg_path)
    except Exception as e:
        print(f"Errore caricamento config: {e}")
        return 1
    log_dir = Path(cfg.logging.log_dir).expanduser()
    print(f"Log directory: {log_dir}")
    if not log_dir.exists():
        print("(nessun log presente)")
        return 0
    for repo_dir in sorted(log_dir.iterdir()):
        if not repo_dir.is_dir():
            continue
        files = sorted(repo_dir.glob("*.jsonl"))
        if files:
            print(f"  {repo_dir.name}: {len(files)} run, ultimo: {files[-1].name}")
    return 0


_DEFAULT_CONFIG_TEMPLATE = '''[gitlab]
base_url = "{base_url}"
token = "{token}"
http_timeout_seconds = 30

[defaults]
develop_branch = "develop"
master_branch = "master"
release_branch_prefix = "release/release-"
default_bump = "{default_bump}"
freeze_commit_msg = "version freeze {{version}}"
bump_commit_msg = "version bump {{next_version}}"
merge_back_commit_msg = "Merge release {{version}} into develop"
mr_master_title = "Release {{version}}"
mr_master_body_template = """
## Release {{version}}

### Scope
TODO

### Rollback
TODO
"""

[behavior]
confirm_before_push = true
confirm_before_mr = true
open_mr_in_browser_after_create = true
mr_develop_strategy = "direct_push"

[logging]
log_dir = "~/.local/state/release-flow/logs"
log_retention_days = 30
verbose_default = false

[project_types.java]
detect = ["pom.xml"]
primary_file = "pom.xml"
secondary_files = ["chart/Chart.yaml", ".helm/Chart.yaml", "pipeline.yaml"]

[project_types.go]
detect = ["go.mod"]
primary_file = "internal/version/version.go"
secondary_files = ["Chart.yaml", "pipeline.yaml"]

[project_types.helm-only]
detect = ["Chart.yaml", "!pom.xml", "!go.mod"]
primary_file = "Chart.yaml"
secondary_files = ["pipeline.yaml"]
'''
