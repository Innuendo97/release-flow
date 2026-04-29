"""State machine: 8 phases + detect_phase() function. Pure module."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from release_flow.gitlab_client import MergeRequest


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
