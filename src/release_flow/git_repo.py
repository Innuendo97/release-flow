"""Wrapper around git via subprocess. No GitPython dependency.

This module is the SOLE place that runs git commands in production.
Write operations on protected branches are rejected at this layer
(see Task 11 for the PROTECTED_BRANCHES enforcement).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from release_flow.exceptions import GitError


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int


class GitRepo:
    def __init__(self, repo_root: Path):
        self.root = Path(repo_root).resolve()

    def _run(
        self, args: list[str], check: bool = True, capture: bool = True
    ) -> GitResult:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=capture,
            text=True,
        )
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        return GitResult(
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            returncode=result.returncode,
        )

    # --- read-only ---

    def is_git_repo(self) -> bool:
        try:
            res = self._run(["rev-parse", "--git-dir"], check=False)
        except FileNotFoundError:
            return False
        return res.returncode == 0

    def current_branch(self) -> str:
        return self._run(["branch", "--show-current"]).stdout.strip()

    def is_working_tree_clean(self) -> bool:
        return self._run(["status", "--porcelain"]).stdout.strip() == ""

    def last_commit_message(self) -> str:
        return self._run(["log", "-1", "--pretty=%B"]).stdout.strip()

    def local_branches(self) -> list[str]:
        out = self._run(["branch", "--format=%(refname:short)"]).stdout
        return [b.strip() for b in out.splitlines() if b.strip()]

    def remote_branches(self, remote: str = "origin") -> list[str]:
        out = self._run(["branch", "-r", "--format=%(refname:short)"]).stdout
        return [b.strip() for b in out.splitlines() if b.strip().startswith(f"{remote}/")]

    def remote_url(self, remote: str = "origin") -> str:
        return self._run(["remote", "get-url", remote]).stdout.strip()

    def branch_exists_local(self, name: str) -> bool:
        return name in self.local_branches()

    def branch_exists_remote(self, name: str, remote: str = "origin") -> bool:
        return f"{remote}/{name}" in self.remote_branches(remote)
