"""Flow orchestrator: pre-flight, branch policy, phase execution."""

from dataclasses import dataclass, field
from typing import Literal

from release_flow.exceptions import FlowError, UserAbortError
from release_flow.git_repo import GitRepo
from release_flow.prompts import Prompter
from release_flow.states import RepoSnapshot
from release_flow.version_bump import BumpType, strip_snapshot
from release_flow.version_io import FileSpec, replace_version_in_files


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


def execute_phase_clean(
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    prompter: Prompter,
    current_version: str,
    release_branch_prefix: str,
    default_bump: BumpType,
) -> None:
    """Phase 0 → 1: create release branch, strip -SNAPSHOT in version files.

    Files are MODIFIED but not committed; that's done in execute_phase_release_branch_created.
    """
    suggested_release_v = strip_snapshot(current_version)
    release_v = prompter.ask(
        "Versione di release", default=suggested_release_v
    )
    suggested_branch = f"{release_branch_prefix}{release_v}"
    branch_name = prompter.ask("Nome release branch", default=suggested_branch)

    git.create_branch(branch_name)
    n = replace_version_in_files(
        primary, secondaries, current_version, release_v
    )
    if n == 0:
        raise FlowError(
            f"no version replacements made for {current_version!r} → {release_v!r}"
        )


def execute_phase_release_branch_created(
    git: GitRepo,
    release_version: str,
    modified_files: list[str],
    prompter: Prompter,
    commit_msg_template: str,
) -> None:
    """Phase 1 → 2: stage modified files and commit freeze."""
    suggested_msg = commit_msg_template.format(version=release_version)
    msg = prompter.ask("Messaggio commit", default=suggested_msg)
    git.add(modified_files)
    git.commit(msg)


def execute_phase_frozen_local(
    git: GitRepo,
    release_branch: str,
    master_branch: str,
    prompter: Prompter,
    confirm_before_push: bool,
) -> None:
    """Phase 2 → 3: pull master into release branch, then push.

    Aborts on non-trivial conflicts during pull master (caller catches GitError).
    """
    git.pull_ff_only("origin", master_branch)  # ff-only — refuses non-FF
    if confirm_before_push:
        confirmed = prompter.confirm(
            f"Push origin {release_branch}?", default=True
        )
        if not confirmed:
            raise UserAbortError("user declined push")
    git.push("origin", release_branch, set_upstream=True)
