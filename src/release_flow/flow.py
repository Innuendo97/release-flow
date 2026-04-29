"""Flow orchestrator: pre-flight, branch policy, phase execution."""

from dataclasses import dataclass, field
from typing import Literal

from release_flow.states import RepoSnapshot


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def run_preflight(snapshot: RepoSnapshot, allow_dirty: bool = False) -> PreflightResult:
    """Run all pre-flight checks. Returns aggregated PreflightResult.

    Pure function over a snapshot — no I/O.
    """
    failures: list[str] = []
    if not snapshot.working_tree_clean and not allow_dirty:
        failures.append(
            "working tree has uncommitted changes — commit/stash them, "
            "or pass --allow-dirty"
        )
    if "origin/develop" not in snapshot.remote_branches:
        failures.append("origin/develop not found — repo not a standard GitFlow repo")
    if "origin/master" not in snapshot.remote_branches:
        failures.append("origin/master not found — recovery requires master branch")
    if not snapshot.secondary_versions_consistent:
        failures.append(
            "version mismatch between primary and secondary files — "
            "run recovery to align before proceeding"
        )
    return PreflightResult(passed=len(failures) == 0, failures=failures)


BranchAction = Literal["proceed", "resume", "switch_to_develop", "stop"]


@dataclass(frozen=True)
class BranchPolicyResult:
    action: BranchAction
    reason: str = ""


def evaluate_branch_policy(
    snapshot: RepoSnapshot,
    feature_has_unmerged_commits: bool = False,
) -> BranchPolicyResult:
    """Decide what to do given the current branch.

    `feature_has_unmerged_commits` must be precomputed by caller (requires git
    log — caller is the orchestrator with a GitRepo handle).
    """
    if snapshot.is_on_develop:
        return BranchPolicyResult(action="proceed")

    if snapshot.is_on_release_branch:
        return BranchPolicyResult(
            action="resume",
            reason=f"resuming flow on existing release branch {snapshot.current_branch}",
        )

    # Feature branch
    if feature_has_unmerged_commits:
        return BranchPolicyResult(
            action="stop",
            reason=(
                f"current branch {snapshot.current_branch!r} has commits not in develop. "
                f"Merge your work via MR → develop first, then rerun."
            ),
        )
    return BranchPolicyResult(
        action="switch_to_develop",
        reason=(
            f"branch {snapshot.current_branch!r} is fully integrated in develop. "
            f"Will checkout develop and proceed."
        ),
    )
