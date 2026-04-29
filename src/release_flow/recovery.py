"""Recovery sub-flows for dirty/anomalous repo states (cases A-F).

Each recovery function returns a `RecoveryPlan` describing what to do.
The orchestrator (flow.py) is responsible for applying the plan via GitRepo.
This separation keeps recovery testable without git I/O.
"""

from dataclasses import dataclass
from enum import StrEnum

from release_flow.exceptions import UserAbortError
from release_flow.prompts import Prompter
from release_flow.states import RepoSnapshot
from release_flow.version_bump import BumpType, bump_version, is_snapshot, to_snapshot


class RecoveryAction(StrEnum):
    CASO_A_BUMP_MISSING = "caso_a_bump_missing"
    CASO_B_VERSIONS_MISALIGNED = "caso_b_versions_misaligned"
    CASO_C_FOREIGN_RELEASE_BRANCH = "caso_c_foreign_release_branch"
    CASO_D_MR_ALREADY_OPEN = "caso_d_mr_already_open"
    CASO_E_DEVELOP_BEHIND = "caso_e_develop_behind"
    CASO_F_MERGE_IN_PROGRESS = "caso_f_merge_in_progress"


@dataclass(frozen=True)
class RecoveryPlan:
    action: RecoveryAction
    from_version: str
    to_version: str
    commit_message: str
    push: bool


def detect_recovery_needed(snapshot: RepoSnapshot) -> RecoveryAction | None:
    """Return the most urgent recovery needed, or None if state is clean."""
    if snapshot.is_on_develop and not is_snapshot(snapshot.primary_version):
        return RecoveryAction.CASO_A_BUMP_MISSING
    if not snapshot.secondary_versions_consistent:
        return RecoveryAction.CASO_B_VERSIONS_MISALIGNED
    if snapshot.develop_behind_origin:
        return RecoveryAction.CASO_E_DEVELOP_BEHIND
    return None


def recover_caso_a(
    snapshot: RepoSnapshot, prompter: Prompter, default_bump: str
) -> RecoveryPlan:
    """Caso A: develop has a non-SNAPSHOT version (previous release didn't bump).

    Propose: bump to next-SNAPSHOT, commit "version bump X-SNAPSHOT", push.
    """
    current = snapshot.primary_version
    bumped = bump_version(current, BumpType(default_bump))
    suggested_next = to_snapshot(bumped)
    answer = prompter.ask(
        f"Develop ha versione {current!r} (non-SNAPSHOT). "
        f"Prossima versione SNAPSHOT?",
        default=suggested_next,
    )
    next_v = answer or suggested_next
    confirmed = prompter.confirm(
        f"Faccio bump {current} → {next_v} su develop e push?",
        default=True,
    )
    if not confirmed:
        raise UserAbortError("user declined caso A recovery")
    return RecoveryPlan(
        action=RecoveryAction.CASO_A_BUMP_MISSING,
        from_version=current,
        to_version=next_v,
        commit_message=f"version bump {next_v}",
        push=True,
    )
