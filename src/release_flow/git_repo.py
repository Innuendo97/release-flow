"""Wrapper around git via subprocess. No GitPython dependency.

This module is the SOLE place that runs git commands in production.
Write operations on protected branches are rejected at this layer
(see Task 11 for the PROTECTED_BRANCHES enforcement).
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from release_flow.exceptions import GitError

# === PROTECTED BRANCHES ===
# These names can NEVER be deleted, force-pushed, or hard-reset by release-flow.
# Hardcoded — not derivable from user config. Belt + suspenders safety.
PROTECTED_BRANCH_NAMES: frozenset[str] = frozenset({"develop", "master", "main"})


def _refuse_if_protected(branch: str, op: str) -> None:
    """Raise ProtectedBranchError if `branch` is in PROTECTED_BRANCH_NAMES.

    HARD-CODED INVARIANT: cannot be bypassed by any flag, config, or argument.
    """
    if branch in PROTECTED_BRANCH_NAMES:
        from release_flow.exceptions import ProtectedBranchError

        raise ProtectedBranchError(
            f"refusing {op!r} on protected branch '{branch}'. "
            f"This is a hard-coded invariant in release-flow and cannot be bypassed."
        )


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

    # --- write ops ---

    def create_branch(self, name: str, base: str | None = None) -> None:
        args = ["checkout", "-b", name]
        if base:
            args.append(base)
        self._run(args)

    def checkout(self, ref: str) -> None:
        self._run(["checkout", ref])

    def add(self, paths: list[str]) -> None:
        self._run(["add", "--", *paths])

    def commit(self, message: str) -> None:
        self._run(["commit", "-m", message])

    def push(self, remote: str, branch: str, set_upstream: bool = False) -> None:
        # Normal (non-force) push is allowed on any branch including develop/master.
        args = ["push"]
        if set_upstream:
            args.append("-u")
        args.extend([remote, branch])
        self._run(args)

    def pull_ff_only(self, remote: str, branch: str) -> None:
        self._run(["pull", "--ff-only", remote, branch])

    def pull_with_merge(self, remote: str, branch: str) -> None:
        """Pull allowing a merge commit if branches have diverged.

        Uses --no-edit to avoid opening an editor for the merge message.
        Raises GitError if there are unresolvable conflicts (left in working tree).
        """
        self._run(["pull", "--no-edit", "--no-rebase", remote, branch])

    def is_ancestor(self, ancestor_ref: str, descendant_ref: str) -> bool:
        """True iff `ancestor_ref` is an ancestor commit of `descendant_ref`.

        Uses `git merge-base --is-ancestor`: exit 0 means yes, exit 1 means no.
        """
        res = self._run(
            ["merge-base", "--is-ancestor", ancestor_ref, descendant_ref],
            check=False,
        )
        return res.returncode == 0

    def last_meaningful_commit_message(
        self, ref: str = "HEAD", lookback: int = 30
    ) -> str:
        """Return the most recent commit subject on `ref` that isn't a
        'version freeze', 'version bump', or a merge commit.

        Useful for auto-populating the MR description with the actual
        user-facing change that triggered the release. Returns an empty
        string if no meaningful commit is found within `lookback` commits.
        """
        skip_prefixes = ("version freeze", "version bump", "Merge ")
        out = self._run(
            ["log", "--pretty=%s", f"-n{lookback}", ref], check=False
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith(skip_prefixes):
                return line
        return ""

    def delete_local_branch(self, name: str) -> None:
        _refuse_if_protected(name, "delete_local_branch")
        self._run(["branch", "-D", name])

    def delete_remote_branch(self, remote: str, name: str) -> None:
        _refuse_if_protected(name, "delete_remote_branch")
        self._run(["push", remote, "--delete", name])

    def force_push(self, remote: str, branch: str) -> None:
        _refuse_if_protected(branch, "force_push")
        self._run(["push", "--force-with-lease", remote, branch])

    def hard_reset_to(self, branch: str, ref: str) -> None:
        _refuse_if_protected(branch, "hard_reset_to")
        # Ensure we're on `branch` first
        self.checkout(branch)
        self._run(["reset", "--hard", ref])
