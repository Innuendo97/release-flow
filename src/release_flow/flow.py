"""Flow orchestrator: pre-flight, branch policy, phase execution."""

from dataclasses import dataclass, field

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
