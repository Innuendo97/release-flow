"""State machine: 8 phases + detect_phase() function. Pure module."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from release_flow.exceptions import FlowError, VersionMismatchError
from release_flow.git_repo import GitRepo
from release_flow.gitlab_client import MergeRequest
from release_flow.version_bump import is_snapshot
from release_flow.version_io import FileSpec, read_all_versions, verify_versions_consistent


class Phase(StrEnum):
    """Release phase states."""

    CLEAN = "CLEAN"
    RELEASE_BRANCH_CREATED = "RELEASE_BRANCH_CREATED"
    FROZEN_LOCAL = "FROZEN_LOCAL"
    FROZEN_PUSHED = "FROZEN_PUSHED"
    MR_MASTER_OPEN = "MR_MASTER_OPEN"
    BUMP_PENDING = "BUMP_PENDING"
    BUMPED_LOCAL = "BUMPED_LOCAL"
    DONE = "DONE"


@dataclass(frozen=True)
class RepoSnapshot:
    """Read-only view of the repo state at a moment in time.

    `detect_phase()` operates on this snapshot — pure function.
    """

    repo_root: Path
    current_branch: str
    working_tree_clean: bool
    primary_version: str
    secondary_versions_consistent: bool
    last_commit_message: str
    local_branches: list[str]
    remote_branches: list[str]
    open_mrs_for_release_branch: list[MergeRequest]
    release_branch_name: str | None  # if current branch matches release prefix
    develop_ahead_of_origin: bool = False
    develop_behind_origin: bool = False

    @property
    def is_on_develop(self) -> bool:
        """Check if currently on develop branch."""
        return self.current_branch == "develop"

    @property
    def is_on_release_branch(self) -> bool:
        """Check if currently on a release branch."""
        return (
            self.release_branch_name is not None
            and self.current_branch == self.release_branch_name
        )


def detect_phase(s: RepoSnapshot) -> Phase:
    """Map a RepoSnapshot to its current Phase. Pure function.

    The phase is derived solely from the snapshot fields, no I/O.
    Order of checks matters: more specific phases first.
    """
    if s.is_on_release_branch:
        # On a release branch — figure out which sub-phase
        if not s.working_tree_clean:
            return Phase.RELEASE_BRANCH_CREATED  # files modified, not committed
        # working tree clean — last commit might be the freeze
        is_freeze_commit = s.last_commit_message.startswith("version freeze")
        on_remote = (
            s.release_branch_name is not None
            and f"origin/{s.release_branch_name}" in s.remote_branches
        )
        if is_freeze_commit and not on_remote:
            return Phase.FROZEN_LOCAL
        if is_freeze_commit and on_remote and not s.open_mrs_for_release_branch:
            return Phase.FROZEN_PUSHED
        if is_freeze_commit and on_remote and s.open_mrs_for_release_branch:
            return Phase.MR_MASTER_OPEN
        # Edge case: clean but no freeze commit — treat as RELEASE_BRANCH_CREATED
        return Phase.RELEASE_BRANCH_CREATED

    if s.is_on_develop:
        # Logic for the develop side of the flow
        is_bump_commit = s.last_commit_message.startswith("version bump")
        if is_bump_commit and s.develop_ahead_of_origin:
            return Phase.BUMPED_LOCAL
        # If we have a release branch with open MR but no bump yet, we're BUMP_PENDING
        if s.open_mrs_for_release_branch and not is_bump_commit:
            return Phase.BUMP_PENDING
        # Otherwise — CLEAN if version is SNAPSHOT and synced; DONE if last commit was a merge of release.
        if is_snapshot(s.primary_version) and not s.develop_ahead_of_origin:
            if "Merge" in s.last_commit_message and "release" in s.last_commit_message.lower():
                return Phase.DONE
            return Phase.CLEAN
        return Phase.CLEAN

    # Not on develop, not on release branch — caller should have refused via branch policy
    raise FlowError(
        f"unexpected branch {s.current_branch!r}: not develop, not a release branch. "
        f"Branch policy should have caught this earlier."
    )


def build_snapshot(
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    release_branch_prefix: str,
    mrs_for_release_branch: list[MergeRequest],
) -> RepoSnapshot:
    """Build a RepoSnapshot from the live state of the repo + GitLab.

    Catches VersionMismatchError and reflects it via
    `secondary_versions_consistent=False` (caller can route to recovery).
    """
    current = git.current_branch()
    release_name = (
        current if current.startswith(release_branch_prefix) else None
    )
    primary_v, _ = read_all_versions(primary, secondaries)
    try:
        verify_versions_consistent(primary, secondaries)
        consistent = True
    except VersionMismatchError:
        consistent = False

    # ahead/behind detection vs origin/develop
    ahead = behind = False
    if "develop" in git.local_branches() and "origin/develop" in git.remote_branches():
        ahead_behind = git._run(
            ["rev-list", "--left-right", "--count", "develop...origin/develop"]
        ).stdout.strip().split()
        if len(ahead_behind) == 2:
            ahead = int(ahead_behind[0]) > 0
            behind = int(ahead_behind[1]) > 0

    return RepoSnapshot(
        repo_root=git.root,
        current_branch=current,
        working_tree_clean=git.is_working_tree_clean(),
        primary_version=primary_v,
        secondary_versions_consistent=consistent,
        last_commit_message=git.last_commit_message(),
        local_branches=git.local_branches(),
        remote_branches=git.remote_branches(),
        open_mrs_for_release_branch=mrs_for_release_branch,
        release_branch_name=release_name,
        develop_ahead_of_origin=ahead,
        develop_behind_origin=behind,
    )
