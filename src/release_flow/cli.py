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
    """Stub for status subcommand (implemented in Task 31)."""
    raise NotImplementedError("status subcommand: implemented in Task 31")


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
