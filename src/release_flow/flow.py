"""Flow orchestrator: pre-flight, branch policy, phase execution."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from release_flow.config import Config, ProjectTypeConfig

if TYPE_CHECKING:
    from release_flow.logging_setup import AuditLogger
from release_flow.exceptions import FlowError, UserAbortError
from release_flow.git_repo import GitRepo
from release_flow.gitlab_client import GitLabClient, MergeRequest
from release_flow.project_detector import detect_project_type
from release_flow.prompts import Prompter
from release_flow.recovery import (
    RecoveryAction,
    apply_caso_a_plan,
    apply_caso_b_alignment,
    apply_caso_e_pull,
    detect_recovery_needed,
    recover_caso_a,
    recover_caso_b,
    recover_caso_e,
)
from release_flow.states import Phase, RepoSnapshot, build_snapshot, detect_phase
from release_flow.version_bump import BumpType, bump_version, strip_snapshot, to_snapshot
from release_flow.version_io import (
    CHART_SECONDARY_PATTERNS,
    PIPELINE_SECONDARY_PATTERN,
    FileSpec,
    read_all_versions,
    replace_version_in_files,
)


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

    Pull allows a merge commit if master has diverged (e.g. hotfixes landed
    directly on master). Aborts via GitError if there are real content
    conflicts that need human resolution.
    """
    git.pull_with_merge("origin", master_branch)
    if confirm_before_push:
        confirmed = prompter.confirm(
            f"Push origin {release_branch}?", default=True
        )
        if not confirmed:
            raise UserAbortError("user declined push")
    git.push("origin", release_branch, set_upstream=True)


def execute_phase_frozen_pushed(
    gitlab: GitLabClient,
    project_path: str,
    release_branch: str,
    master_branch: str,
    release_version: str,
    prompter: Prompter,
    mr_title_template: str,
    mr_body_template: str,
    confirm_before_mr: bool,
    repo_name: str = "",
    last_commit_message: str = "",
) -> MergeRequest | None:
    """Phase 3 → 4: create MR release_branch → master. Idempotent.

    Returns the MergeRequest on success, or None if the user explicitly
    declined to create the MR (caller can decide whether to continue with
    the bump-back step or exit).

    Title and body templates support placeholders:
      - {version}              — the release version, e.g. "1.1.30"
      - {repo_name}            — the repo / microservice name
      - {last_commit_message}  — last meaningful commit before the freeze
    Templates that don't reference a placeholder simply ignore it.
    """
    # Idempotency: if MR already exists, return it
    existing = gitlab.list_open_mrs(project_path, source_branch=release_branch)
    target_match = [mr for mr in existing if mr.target_branch == master_branch]
    if target_match:
        return target_match[0]

    # Upfront confirmation: ask BEFORE bothering the user with title/body.
    if confirm_before_mr:
        confirmed = prompter.confirm(
            f"Crei la MR {release_branch} → {master_branch} ora?", default=True
        )
        if not confirmed:
            return None  # signal to caller: user declined

    fmt_kwargs = {
        "version": release_version,
        "repo_name": repo_name,
        "last_commit_message": last_commit_message,
    }
    suggested_title = mr_title_template.format(**fmt_kwargs)
    title = prompter.ask("Titolo MR", default=suggested_title)
    initial_body = mr_body_template.format(**fmt_kwargs)
    body = prompter.edit_text(initial=initial_body)

    return gitlab.create_mr(
        project_path=project_path,
        source_branch=release_branch,
        target_branch=master_branch,
        title=title,
        description=body,
    )


def execute_phase_mr_master_open(git: GitRepo, develop_branch: str) -> None:
    """Phase 4 → 5: switch to develop. The MR for master remains open
    awaiting client approval — does NOT block the bump-back."""
    git.checkout(develop_branch)


def execute_phase_bump_pending(
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    prompter: Prompter,
    current_version: str,
    default_bump: BumpType,
    commit_msg_template: str,
    confirm_before_bump: bool = True,
) -> str:
    """Phase 5 → 6: bump SNAPSHOT version on develop, commit.

    Returns the new version string.

    If `confirm_before_bump` is True (default), asks the user upfront whether
    to prepare develop for the next iteration. Declining raises UserAbortError;
    the user is warned that the next release will detect the missing bump
    via Caso A recovery.
    """
    if confirm_before_bump:
        confirmed = prompter.confirm(
            f"Vuoi preparare develop per la prossima iterazione di sviluppo "
            f"(bump SNAPSHOT da {current_version} a quella successiva)?",
            default=True,
        )
        if not confirmed:
            raise UserAbortError(
                f"Bump declined. Develop resta a {current_version}. "
                f"Ricorda di bumpare prima della prossima release "
                f"(release-flow lo rileverà come Caso A e lo proporrà in automatico)."
            )

    bumped = bump_version(strip_snapshot(current_version), default_bump)
    suggested_next = to_snapshot(bumped)
    next_v = prompter.ask("Prossima versione SNAPSHOT", default=suggested_next)
    suggested_msg = commit_msg_template.format(next_version=next_v)
    msg = prompter.ask("Messaggio commit", default=suggested_msg)

    n = replace_version_in_files(primary, secondaries, current_version, next_v)
    if n == 0:
        raise FlowError(f"no version replacements for bump {current_version!r} → {next_v!r}")

    files_to_add = [str(primary.path.relative_to(git.root))]
    for sec in secondaries:
        files_to_add.append(str(sec.path.relative_to(git.root)))
    git.add(files_to_add)
    git.commit(msg)
    return next_v


def execute_phase_bumped_local(
    git: GitRepo,
    release_branch: str,
    develop_branch: str,
    version_files: list[Path],
    prompter: Prompter,
    merge_msg_template: str,
    release_version: str,
    confirm_before_push: bool,
) -> None:
    """Phase 6 → 7: merge release branch into develop, resolving conflicts
    on version_files with --ours (keep develop's bumped version).

    Refuses if conflicts exist on files OUTSIDE the version_files set.
    """
    # Trigger pull (creates merge with conflict)
    git._run(
        ["pull", "origin", release_branch, "--no-edit", "--no-rebase"],
        check=False,
    )

    # Detect unmerged paths
    unmerged_out = git._run(
        ["diff", "--name-only", "--diff-filter=U"], check=False
    ).stdout.strip()
    unmerged = [u for u in unmerged_out.splitlines() if u]

    version_paths = {str(p.relative_to(git.root)).replace("\\", "/") for p in version_files}
    # Normalize unmerged paths too (git outputs forward slashes)
    foreign = [u for u in unmerged if u not in version_paths]
    if foreign:
        raise FlowError(
            f"merge-back has conflicts on non-version files: {foreign}. "
            f"Aborting auto-resolution. Resolve manually then commit."
        )

    if unmerged:
        confirmed = prompter.confirm(
            f"Conflitti solo su file di versione: {sorted(unmerged)}. "
            f"Risolvo con --ours (mantengo versione di develop)?",
            default=True,
        )
        if not confirmed:
            raise UserAbortError("user declined --ours resolution")

        # Resolve each version file with our version (the bumped one)
        for path in version_paths & set(unmerged):
            git._run(["checkout", "--ours", "--", path])
            git._run(["add", "--", path])

        merge_msg = merge_msg_template.format(version=release_version)
        git._run(["commit", "--no-edit", "-m", merge_msg])

    if confirm_before_push:
        confirmed = prompter.confirm("Push origin develop?", default=True)
        if not confirmed:
            raise UserAbortError("user declined push develop")
    git.push("origin", develop_branch)


# Built-in pattern map for known files. Used to construct FileSpec from
# config's bare-path lists.
BUILTIN_PATTERNS: dict[str, list[str]] = {
    "pom.xml": [r"<artifactId>[^<]+</artifactId>\s*<version>(?P<v>[^<]+)</version>"],
    "Chart.yaml": CHART_SECONDARY_PATTERNS,
    "chart/Chart.yaml": CHART_SECONDARY_PATTERNS,
    ".helm/Chart.yaml": CHART_SECONDARY_PATTERNS,
    "pipeline.yaml": [PIPELINE_SECONDARY_PATTERN],
    "package.json": [r'^\s{0,4}"version":\s*"(?P<v>[^"]+)"'],
}


@dataclass(frozen=True)
class FlowResult:
    final_phase: Phase
    created_mr: MergeRequest | None = None
    final_version: str = ""


def _build_filespecs(
    repo_root: Path, project_type: ProjectTypeConfig
) -> tuple[FileSpec, list[FileSpec]]:
    primary = FileSpec(
        path=repo_root / project_type.primary_file,
        patterns=BUILTIN_PATTERNS.get(project_type.primary_file, []),
    )
    secondaries = [
        FileSpec(
            path=repo_root / f,
            patterns=BUILTIN_PATTERNS.get(f, BUILTIN_PATTERNS.get(Path(f).name, [])),
        )
        for f in project_type.secondary_files
        if (repo_root / f).exists()
    ]
    return primary, secondaries


def run(
    repo_root: Path,
    config: Config,
    gitlab: GitLabClient,
    prompter: Prompter,
    allow_dirty: bool = False,
    project_path: str | None = None,
    audit_logger: "AuditLogger | None" = None,
) -> FlowResult:
    """Top-level orchestrator. Detects project type, builds snapshot,
    runs pre-flight + branch policy + recovery + phase loop until DONE.

    `project_path` is the GitLab namespace/repo path (e.g. 'org/app').
    If omitted it is derived from the git remote URL.
    """
    git = GitRepo(repo_root)

    # 1. Detect project type
    project_type_name = detect_project_type(
        repo_root, {n: {"detect": pt.detect} for n, pt in config.project_types.items()}
    )
    project_type = config.project_types[project_type_name]
    primary, secondaries = _build_filespecs(repo_root, project_type)

    # 2. Get GitLab project path (from arg or derived from git remote URL)
    if project_path is None:
        project_path = gitlab.project_path_from_url(git.remote_url("origin"))

    # 3. Snapshot + recovery + branch policy + phase loop
    created_mr: MergeRequest | None = None
    max_iterations = 20  # safety limit
    for _ in range(max_iterations):
        # fetch open MRs filtered by potential release branch
        possible_release_branches: set[str] = set()
        for b in git.local_branches():
            if b.startswith(config.defaults.release_branch_prefix):
                possible_release_branches.add(b)
        for b in git.remote_branches():
            stripped = b.replace("origin/", "", 1)
            if stripped.startswith(config.defaults.release_branch_prefix):
                possible_release_branches.add(stripped)

        mrs: list[MergeRequest] = []
        for rb in sorted(possible_release_branches):
            mrs.extend(gitlab.list_open_mrs(project_path, source_branch=rb))

        snapshot = build_snapshot(
            git=git, primary=primary, secondaries=secondaries,
            release_branch_prefix=config.defaults.release_branch_prefix,
            mrs_for_release_branch=mrs,
        )

        # Pre-flight
        # Allow dirty working tree when on a release branch: RELEASE_BRANCH_CREATED is
        # intentionally dirty (version files changed but not yet committed).
        effective_allow_dirty = allow_dirty or snapshot.is_on_release_branch
        pre = run_preflight(snapshot, allow_dirty=effective_allow_dirty)
        recovery_action = detect_recovery_needed(snapshot)
        if not pre.passed and recovery_action is None:
            raise FlowError("pre-flight failed: " + "; ".join(pre.failures))

        # Recovery (if needed) — auto-handle the common cases
        if recovery_action is not None:
            print(f"\n⚠ Anomalia rilevata: {recovery_action.value}")
            _handle_recovery(
                recovery_action=recovery_action,
                snapshot=snapshot,
                git=git,
                primary=primary,
                secondaries=secondaries,
                prompter=prompter,
                config=config,
            )
            # After recovery, ask if user wants to proceed
            cont = prompter.confirm(
                "\nRecovery completato. Vuoi proseguire con il flusso di release?",
                default=True,
            )
            if not cont:
                print(
                    "Uscita richiesta dall'utente. Lo stato del repo è ora pulito; "
                    "rilancia 'release-flow' quando vuoi procedere con la release."
                )
                return FlowResult(
                    final_phase=Phase.CLEAN,
                    created_mr=created_mr,
                    final_version="",
                )
            # Re-evaluate snapshot from scratch on next loop iteration
            continue

        # Branch policy (only when not on develop or release branch)
        if not (snapshot.is_on_develop or snapshot.is_on_release_branch):
            policy = evaluate_branch_policy(snapshot, feature_has_unmerged_commits=False)
            if policy.action == "stop":
                raise FlowError(policy.reason)
            if policy.action == "switch_to_develop":
                git.checkout(config.defaults.develop_branch)
                continue

        # Orphan release-branch detection: if we're on develop and there are
        # release branches in origin without an open MR, offer to create the
        # MR for one of them (instead of starting a new release).
        if snapshot.is_on_develop:
            orphan = _find_orphan_release_branch(
                git=git,
                mrs=mrs,
                release_branch_prefix=config.defaults.release_branch_prefix,
            )
            if orphan is not None:
                print(
                    f"\n  i  Trovato release branch su origin senza MR: {orphan}"
                )
                if prompter.confirm(
                    f"Vuoi creare la MR per {orphan} → {config.defaults.master_branch} ora? "
                    f"(Se No, procedo con una nuova release.)",
                    default=True,
                ):
                    # Switch to the orphan release branch (fetch locally if needed)
                    if orphan in git.local_branches():
                        git.checkout(orphan)
                    else:
                        git._run(["fetch", "origin", orphan], check=False)
                        git._run(["checkout", "-b", orphan, f"origin/{orphan}"])
                    print(f"  ✓ Switch a {orphan}")
                    continue  # re-detect, will be FROZEN_PUSHED → MR creation

        # Detect and execute phase
        phase = detect_phase(snapshot)
        if audit_logger is not None:
            audit_logger.log_event(
                level="info", phase=phase.value, action="execute_phase",
                extra={
                    "branch": snapshot.current_branch,
                    "version": snapshot.primary_version,
                },
            )
        if phase == Phase.DONE:
            _print_done_summary(
                snapshot=snapshot, created_mr=created_mr, config=config,
            )
            return FlowResult(
                final_phase=phase,
                created_mr=created_mr,
                final_version=snapshot.primary_version,
            )

        _print_phase_header(phase)

        if phase == Phase.CLEAN:
            execute_phase_clean(
                git=git, primary=primary, secondaries=secondaries,
                prompter=prompter, current_version=snapshot.primary_version,
                release_branch_prefix=config.defaults.release_branch_prefix,
                default_bump=BumpType(config.defaults.default_bump),
            )
        elif phase == Phase.RELEASE_BRANCH_CREATED:
            modified = [str(primary.path.relative_to(repo_root)).replace("\\", "/")]
            modified.extend(
                str(s.path.relative_to(repo_root)).replace("\\", "/") for s in secondaries
            )
            release_v = strip_snapshot(snapshot.primary_version)
            execute_phase_release_branch_created(
                git=git, release_version=release_v, modified_files=modified,
                prompter=prompter,
                commit_msg_template=config.defaults.freeze_commit_msg,
            )
        elif phase == Phase.FROZEN_LOCAL:
            execute_phase_frozen_local(
                git=git, release_branch=snapshot.current_branch,
                master_branch=config.defaults.master_branch,
                prompter=prompter,
                confirm_before_push=config.behavior.confirm_before_push,
            )
        elif phase == Phase.FROZEN_PUSHED:
            release_v = snapshot.primary_version
            # Compute defaults for MR title/body templates
            repo_name = git.root.name
            last_commit_msg = git.last_meaningful_commit_message()
            mr = execute_phase_frozen_pushed(
                gitlab=gitlab, project_path=project_path,
                release_branch=snapshot.current_branch,
                master_branch=config.defaults.master_branch,
                release_version=release_v, prompter=prompter,
                mr_title_template=config.defaults.mr_master_title,
                mr_body_template=config.defaults.mr_master_body_template,
                confirm_before_mr=config.behavior.confirm_before_mr,
                repo_name=repo_name,
                last_commit_message=last_commit_msg,
            )
            if mr is None:
                # User declined MR. Offer the bump-only path on develop.
                return _handle_no_mr_branch(
                    git=git, primary=primary, secondaries=secondaries,
                    prompter=prompter, config=config,
                    release_branch=snapshot.current_branch,
                )
            created_mr = mr
        elif phase == Phase.MR_MASTER_OPEN:
            execute_phase_mr_master_open(
                git=git, develop_branch=config.defaults.develop_branch
            )
        elif phase == Phase.BUMP_PENDING:
            execute_phase_bump_pending(
                git=git, primary=primary, secondaries=secondaries,
                prompter=prompter, current_version=snapshot.primary_version,
                default_bump=BumpType(config.defaults.default_bump),
                commit_msg_template=config.defaults.bump_commit_msg,
                confirm_before_bump=config.behavior.confirm_before_bump,
            )
        elif phase == Phase.BUMPED_LOCAL:
            # Prefer the release branch tracked by an open MR (works even if
            # the release branch isn't checked out locally). Fall back to any
            # local release branch.
            release_branch = ""
            if snapshot.open_mrs_for_release_branch:
                release_branch = snapshot.open_mrs_for_release_branch[0].source_branch
            else:
                local_release_branches = [
                    b for b in snapshot.local_branches
                    if b.startswith(config.defaults.release_branch_prefix)
                ]
                if local_release_branches:
                    release_branch = local_release_branches[0]
            if not release_branch:
                raise FlowError(
                    "BUMPED_LOCAL phase reached but no release branch found "
                    "(neither in local nor in open MRs)."
                )
            release_v = release_branch.replace(config.defaults.release_branch_prefix, "")
            version_files = [primary.path] + [s.path for s in secondaries]
            execute_phase_bumped_local(
                git=git, release_branch=release_branch,
                develop_branch=config.defaults.develop_branch,
                version_files=version_files, prompter=prompter,
                merge_msg_template=config.defaults.merge_back_commit_msg,
                release_version=release_v,
                confirm_before_push=config.behavior.confirm_before_push,
            )
        else:
            raise FlowError(f"unhandled phase: {phase}")

    raise FlowError(f"orchestrator exceeded {max_iterations} iterations without reaching DONE")


_PHASE_DESCRIPTIONS: dict[Phase, tuple[str, str]] = {
    Phase.CLEAN: (
        "Preparazione release branch",
        "Creo il release branch da develop e rimuovo -SNAPSHOT dai file di versione.",
    ),
    Phase.RELEASE_BRANCH_CREATED: (
        "Commit del freeze",
        "Committo le modifiche fatte ai file di versione (rimozione -SNAPSHOT).",
    ),
    Phase.FROZEN_LOCAL: (
        "Pull master + push del release branch",
        "Allineo il release branch con master, poi push su origin.",
    ),
    Phase.FROZEN_PUSHED: (
        "Creazione MR verso master",
        "Creo la merge request del release branch verso master via API GitLab.",
    ),
    Phase.MR_MASTER_OPEN: (
        "Switch su develop",
        "MR aperta in attesa cliente. Procedo subito col bump-back su develop "
        "(non aspetto l'approvazione cliente).",
    ),
    Phase.BUMP_PENDING: (
        "Bump SNAPSHOT su develop",
        "Bumpo develop alla prossima versione SNAPSHOT (per il prossimo ciclo di sviluppo).",
    ),
    Phase.BUMPED_LOCAL: (
        "Merge-back e push develop",
        "Mergio il release branch in develop con --ours sui file di versione, "
        "poi push develop.",
    ),
}


def _print_phase_header(phase: Phase) -> None:
    """Print a clear separator and description before each phase action."""
    title, desc = _PHASE_DESCRIPTIONS.get(phase, (phase.value, ""))
    print(f"\n▸ Fase {phase.value} — {title}")
    if desc:
        print(f"  {desc}")


def _print_done_summary(
    snapshot: RepoSnapshot,
    created_mr: MergeRequest | None,
    config: Config,
) -> None:
    """Print a rich summary when the flow reaches DONE."""
    print("\n─── ✓ DONE — release flow completato ───")
    if created_mr:
        # Extract the release version from the MR's source branch (e.g.
        # "release/release-1.1.29" → "1.1.29").
        release_v = created_mr.source_branch.replace(
            config.defaults.release_branch_prefix, ""
        )
        print(f"  Release {release_v}: file frozen, branch {created_mr.source_branch} pushed")
        print(f"  MR: !{created_mr.iid} → {config.defaults.master_branch}")
        print(f"       {created_mr.web_url}")
        print("       (in attesa approvazione cliente per finalizzare su master)")
    print(f"  Develop: ora a {snapshot.primary_version} (sync con origin)")
    print()


def _find_orphan_release_branch(
    git: GitRepo,
    mrs: list[MergeRequest],
    release_branch_prefix: str,
) -> str | None:
    """Find a release branch that is pushed on origin but has no open MR.

    Returns the branch name (e.g. 'release/release-1.1.14') if exactly one
    such branch exists, or the most recent (last in lexicographic order)
    when multiple exist. Returns None if there are no orphans.

    Used by the orchestrator to detect "I declined the MR last time but now
    I want to create it" — instead of treating develop's state as CLEAN and
    starting a new release.
    """
    remote_release_branches = [
        b.replace("origin/", "", 1)
        for b in git.remote_branches()
        if b.startswith(f"origin/{release_branch_prefix}")
    ]
    mr_source_branches = {mr.source_branch for mr in mrs}
    orphans = [rb for rb in remote_release_branches if rb not in mr_source_branches]
    if not orphans:
        return None
    # Pick the most recent (highest version) — lexicographic sort works for
    # the common 'release/release-X.Y.Z' format.
    return sorted(orphans)[-1]


def _handle_no_mr_branch(
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    prompter: Prompter,
    config: Config,
    release_branch: str,
) -> "FlowResult":
    """Handle the path where the user declined to create the MR.

    The release branch is already pushed (work persisted on origin), so the
    user can create the MR manually on GitLab or rerun release-flow later.
    Meanwhile, we still offer to prepare develop for the next iteration
    (= bump SNAPSHOT). The merge-back step is skipped because it only makes
    sense after the freeze commit lands on master via the MR.
    """
    print(
        f"\n  i  MR non creata. Il release branch {release_branch} è già pushato "
        f"su origin: puoi crearla manualmente su GitLab o rilanciare release-flow."
    )
    git.checkout(config.defaults.develop_branch)
    print(f"  ✓ Switch a {config.defaults.develop_branch}")

    # Read develop's current version (the SNAPSHOT before bump)
    develop_primary_v, _ = read_all_versions(primary, secondaries)

    # confirm_before_bump=True means the user is asked again here. If they
    # decline, UserAbortError propagates up to main() and exits cleanly.
    next_v = execute_phase_bump_pending(
        git=git, primary=primary, secondaries=secondaries,
        prompter=prompter, current_version=develop_primary_v,
        default_bump=BumpType(config.defaults.default_bump),
        commit_msg_template=config.defaults.bump_commit_msg,
        confirm_before_bump=config.behavior.confirm_before_bump,
    )

    # Push develop
    if config.behavior.confirm_before_push and not prompter.confirm(
        "Push origin develop?", default=True
    ):
        raise UserAbortError("user declined push develop")
    git.push("origin", config.defaults.develop_branch)
    print(f"  ✓ Push origin {config.defaults.develop_branch}")

    print("\n─── ✓ DONE — flow parziale completato ───")
    print(f"  Release branch {release_branch}: pushato su origin (MR da creare manualmente)")
    print(f"  Develop: ora a {next_v} (sync con origin)")
    print()

    return FlowResult(
        final_phase=Phase.DONE,
        created_mr=None,
        final_version=next_v,
    )


def _handle_recovery(
    recovery_action: RecoveryAction,
    snapshot: RepoSnapshot,
    git: GitRepo,
    primary: FileSpec,
    secondaries: list[FileSpec],
    prompter: Prompter,
    config: Config,
) -> None:
    """Dispatch a recovery action: run the corresponding decision function +
    apply function. Raises UserAbortError or RecoveryError on failure."""
    if recovery_action == RecoveryAction.CASO_A_BUMP_MISSING:
        print(
            f"  Develop ha versione {snapshot.primary_version!r} (non-SNAPSHOT). "
            f"La release precedente non ha bumpato develop."
        )
        plan = recover_caso_a(
            snapshot, prompter, default_bump=config.defaults.default_bump
        )
        apply_caso_a_plan(
            git, primary, secondaries, plan,
            develop_branch=config.defaults.develop_branch,
        )
        return

    if recovery_action == RecoveryAction.CASO_B_VERSIONS_MISALIGNED:
        primary_v, secondary_matches = read_all_versions(primary, secondaries)
        divergent_versions = sorted(
            {m.matched_version for m in secondary_matches if m.matched_version != primary_v}
        )
        print("  Versioni rilevate nei file:")
        print(f"    {primary.path.name} (primary): {primary_v}")
        for m in secondary_matches:
            mark = "✗" if m.matched_version != primary_v else "✓"
            rel = m.file.relative_to(git.root) if m.file.is_absolute() else m.file
            print(f"    {mark} {rel}:{m.line}  {m.matched_version}")
        choice = recover_caso_b(snapshot, prompter, primary_v, divergent_versions)
        apply_caso_b_alignment(
            git, primary, secondaries, choice,
            develop_branch=config.defaults.develop_branch,
        )
        return

    if recovery_action == RecoveryAction.CASO_E_DEVELOP_BEHIND:
        print("  Develop locale è indietro rispetto a origin.")
        recover_caso_e(prompter, behind_count=1)  # behind_count is informational
        apply_caso_e_pull(git, develop_branch=config.defaults.develop_branch)
        return

    raise FlowError(
        f"recovery action {recovery_action.value} non implementato. "
        f"Sistema a mano e rilancia."
    )
