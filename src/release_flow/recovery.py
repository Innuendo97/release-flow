"""Recovery sub-flows for dirty/anomalous repo states (cases A-F).

Each `recover_caso_*` function returns a plan (RecoveryPlan / AlignmentChoice / str)
describing what to do. The corresponding `apply_caso_*` function executes it via
GitRepo, with verbose step-by-step output.

This separation keeps the decision logic testable without git I/O, while the apply
functions encapsulate the side effects.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from release_flow.exceptions import RecoveryError, UserAbortError
from release_flow.git_repo import GitRepo
from release_flow.prompts import Prompter
from release_flow.states import RepoSnapshot
from release_flow.version_bump import (
    BumpType,
    bump_version,
    is_snapshot,
    normalize_snapshot,
    to_snapshot,
)
from release_flow.version_io import (
    FileSpec,
    read_all_versions,
    replace_version_in_files,
    write_version_in_file,
)


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


@dataclass(frozen=True)
class AlignmentChoice:
    authoritative_version: str


def recover_caso_b(
    snapshot: RepoSnapshot,
    prompter: Prompter,
    primary_version: str,
    divergent_versions: list[str],
) -> AlignmentChoice:
    """Caso B: secondary file versions disagree with primary. Ask user
    which version is authoritative; orchestrator will then propagate it."""
    candidates = sorted({primary_version, *divergent_versions})
    choice = prompter.ask(
        f"Versioni disallineate. Quale è autoritativa? (candidati: {candidates})",
        default=primary_version,
    )
    if choice not in candidates:
        raise RecoveryError(f"version {choice!r} not among detected candidates")
    confirmed = prompter.confirm(
        f"Allineo tutti i file a {choice!r}?", default=True
    )
    if not confirmed:
        raise UserAbortError("user declined caso B recovery")
    return AlignmentChoice(authoritative_version=choice)


def recover_caso_c(
    prompter: Prompter,
    branch_author: str,
    current_user: str,
) -> str:
    """Caso C: release branch already exists in remote.

    If me → resume; if other → STOP.
    """
    if branch_author == current_user:
        confirmed = prompter.confirm(
            "Sembra che tu abbia già iniziato questa release. Riprendo da dove avevi lasciato?",
            default=True,
        )
        return "resume" if confirmed else "stop"
    return "stop"


def recover_caso_d(prompter: Prompter, mr_iid: int, mr_url: str) -> str:
    """Caso D: MR already open. Continue with bump-back."""
    confirmed = prompter.confirm(
        f"MR !{mr_iid} ({mr_url}) già aperta. Continuo con il bump-back su develop?",
        default=True,
    )
    return "continue_to_bump" if confirmed else "stop"


def recover_caso_e(prompter: Prompter, behind_count: int) -> str:
    """Caso E: develop is N commits behind origin. Propose ff-only pull."""
    confirmed = prompter.confirm(
        f"Develop locale è {behind_count} commit indietro rispetto a origin. "
        f"Faccio 'git pull --ff-only origin develop'?",
        default=True,
    )
    if not confirmed:
        raise UserAbortError("user declined caso E recovery")
    return "pull_ff_only"


def recover_caso_f() -> None:
    """Caso F: merge already in progress. Unconditional STOP."""
    raise RecoveryError(
        "repo is in the middle of an unresolved merge. "
        "Resolve or abort the merge yourself ('git merge --abort'), then rerun."
    )


# ---------------------------------------------------------------------------
# Apply functions: execute a recovery plan against a real GitRepo, with
# verbose step-by-step output to stdout.
# ---------------------------------------------------------------------------


def apply_caso_a_plan(
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    plan: RecoveryPlan,
    develop_branch: str = "develop",
) -> None:
    """Apply a Caso A recovery plan: bump version files, commit, optionally push."""
    print(f"  → Modifico file di versione: {plan.from_version} → {plan.to_version}")
    n = replace_version_in_files(primary, secondaries, plan.from_version, plan.to_version)
    print(f"    {n} occorrenze sostituite")

    files = [str(primary.path.relative_to(git.root)).replace("\\", "/")]
    files.extend(
        str(s.path.relative_to(git.root)).replace("\\", "/") for s in secondaries
    )
    print(f"  → git add {' '.join(files)}")
    git.add(files)

    print(f'  → git commit -m "{plan.commit_message}"')
    git.commit(plan.commit_message)

    if plan.push:
        print(f"  → git push origin {develop_branch}")
        git.push("origin", develop_branch)

    print("  ✓ Recovery Caso A completato")


def apply_caso_b_alignment(
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    choice: AlignmentChoice,
    develop_branch: str = "develop",
) -> None:
    """Apply a Caso B recovery: align all files to the authoritative version.

    Comparison is normalized: a `+SNAPSHOT` value is considered equal to its
    `-SNAPSHOT` counterpart, so files using different SNAPSHOT separators
    won't be flagged as divergent on that basis alone.
    """
    target = choice.authoritative_version
    target_norm = normalize_snapshot(target)
    print(f"  → Allineo tutti i file alla versione {target!r}")

    primary_v, secondary_matches = read_all_versions(primary, secondaries)

    files_changed: set[Path] = set()

    if normalize_snapshot(primary_v) != target_norm:
        for pattern in primary.patterns:
            n = write_version_in_file(primary.path, primary_v, target, pattern)
            if n > 0:
                print(f"    {primary.path.name}: {primary_v} → {target}")
                files_changed.add(primary.path)

    divergent_versions = {
        m.matched_version for m in secondary_matches
        if normalize_snapshot(m.matched_version) != target_norm
    }
    for old_v in divergent_versions:
        for spec in secondaries:
            for pattern in spec.patterns:
                n = write_version_in_file(spec.path, old_v, target, pattern)
                if n > 0:
                    print(f"    {spec.path.name}: {old_v} → {target}")
                    files_changed.add(spec.path)

    if not files_changed:
        print("    Nulla da fare (già allineato).")
        return

    files = sorted(
        str(p.relative_to(git.root)).replace("\\", "/") for p in files_changed
    )
    print(f"  → git add {' '.join(files)}")
    git.add(files)

    msg = f"fix: align versions to {target}"
    print(f'  → git commit -m "{msg}"')
    git.commit(msg)

    print(f"  → git push origin {develop_branch}")
    git.push("origin", develop_branch)

    print("  ✓ Recovery Caso B completato")


def apply_caso_e_pull(
    git: GitRepo,
    develop_branch: str = "develop",
) -> None:
    """Apply a Caso E recovery: fast-forward pull develop from origin."""
    print(f"  → git pull --ff-only origin {develop_branch}")
    git.pull_ff_only("origin", develop_branch)
    print("  ✓ Recovery Caso E completato")
