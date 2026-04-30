"""CLI entry point: argparse + subcommand dispatch."""

import argparse
import sys
from pathlib import Path

from release_flow import __version__


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


def _cmd_init(args: argparse.Namespace) -> int:
    """Stub for init subcommand (implemented in Task 32)."""
    raise NotImplementedError("init subcommand: implemented in Task 32")


def _cmd_doctor(args: argparse.Namespace) -> int:
    """Stub for doctor subcommand (implemented in Task 33)."""
    raise NotImplementedError("doctor subcommand: implemented in Task 33")


def _cmd_abort(args: argparse.Namespace) -> int:
    """Stub for abort subcommand (implemented in Task 33)."""
    raise NotImplementedError("abort subcommand: implemented in Task 33")


def _cmd_config_edit(args: argparse.Namespace) -> int:
    """Stub for config-edit subcommand (implemented in Task 33)."""
    raise NotImplementedError("config-edit subcommand: implemented in Task 33")


def _cmd_logs(args: argparse.Namespace) -> int:
    """Stub for logs subcommand (implemented in Task 33)."""
    raise NotImplementedError("logs subcommand: implemented in Task 33")
