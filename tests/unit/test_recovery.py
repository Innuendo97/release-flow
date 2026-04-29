"""Tests for recovery sub-flows (Caso A)."""

from pathlib import Path

import pytest

from release_flow.exceptions import RecoveryError, UserAbortError
from release_flow.prompts import ScriptedPrompter
from release_flow.recovery import (
    RecoveryAction,
    detect_recovery_needed,
    recover_caso_a,
    recover_caso_b,
    recover_caso_c,
    recover_caso_d,
    recover_caso_e,
    recover_caso_f,
)
from release_flow.states import RepoSnapshot


def _snapshot(**overrides) -> RepoSnapshot:
    base = dict(
        repo_root=Path("/tmp/x"),
        current_branch="develop",
        working_tree_clean=True,
        primary_version="1.0.0-SNAPSHOT",
        secondary_versions_consistent=True,
        last_commit_message="msg",
        local_branches=["develop", "master"],
        remote_branches=["origin/develop", "origin/master"],
        open_mrs_for_release_branch=[],
        release_branch_name=None,
    )
    base.update(overrides)
    return RepoSnapshot(**base)


class TestDetectRecoveryNeeded:
    def test_clean_state_no_recovery(self):
        s = _snapshot()
        assert detect_recovery_needed(s) is None

    def test_non_snapshot_on_develop_triggers_caso_a(self):
        s = _snapshot(primary_version="1.0.0")  # NO -SNAPSHOT
        assert detect_recovery_needed(s) == RecoveryAction.CASO_A_BUMP_MISSING

    def test_inconsistent_versions_triggers_caso_b(self):
        s = _snapshot(secondary_versions_consistent=False)
        assert detect_recovery_needed(s) == RecoveryAction.CASO_B_VERSIONS_MISALIGNED


class TestRecoverCasoA:
    def test_user_confirms_bump_returns_action(self):
        s = _snapshot(primary_version="1.0.0")  # missing SNAPSHOT
        prompter = ScriptedPrompter()
        prompter.queue(["1.0.1-SNAPSHOT", "yes"])  # next version, confirm
        plan = recover_caso_a(s, prompter, default_bump="patch")
        assert plan.from_version == "1.0.0"
        assert plan.to_version == "1.0.1-SNAPSHOT"
        # commit message contains version
        assert "1.0.1-SNAPSHOT" in plan.commit_message

    def test_user_aborts(self):
        s = _snapshot(primary_version="1.0.0")
        prompter = ScriptedPrompter()
        prompter.queue(["1.0.1-SNAPSHOT", "no"])
        with pytest.raises(UserAbortError):
            recover_caso_a(s, prompter, default_bump="patch")


class TestRecoverCasoB:
    def test_chooses_primary_version(self):
        s = _snapshot(secondary_versions_consistent=False)
        prompter = ScriptedPrompter()
        prompter.queue(["1.1.27", "yes"])  # choose 1.1.27 as authoritative
        choice = recover_caso_b(
            s,
            prompter,
            primary_version="1.1.27",
            divergent_versions=["1.1.26"],
        )
        assert choice.authoritative_version == "1.1.27"


class TestRecoverCasoC:
    def test_my_branch_resumes(self):
        prompter = ScriptedPrompter()
        prompter.queue(["yes"])  # confirm resume
        action = recover_caso_c(prompter, branch_author="me", current_user="me")
        assert action == "resume"

    def test_foreign_branch_stops(self):
        prompter = ScriptedPrompter()
        # No prompt needed — automatic stop
        action = recover_caso_c(prompter, branch_author="marco.rossi", current_user="me")
        assert action == "stop"


class TestRecoverCasoD:
    def test_mr_open_continues(self):
        prompter = ScriptedPrompter()
        prompter.queue(["yes"])
        action = recover_caso_d(prompter, mr_iid=142, mr_url="https://x")
        assert action == "continue_to_bump"


class TestRecoverCasoE:
    def test_pull_ff_only_proposed(self):
        prompter = ScriptedPrompter()
        prompter.queue(["yes"])
        action = recover_caso_e(prompter, behind_count=3)
        assert action == "pull_ff_only"

    def test_user_declines(self):
        prompter = ScriptedPrompter()
        prompter.queue(["no"])
        with pytest.raises(UserAbortError):
            recover_caso_e(prompter, behind_count=3)


class TestRecoverCasoF:
    def test_always_stops(self):
        # Caso F is unconditional STOP — merge in progress
        with pytest.raises(RecoveryError) as exc:
            recover_caso_f()
        assert "merge" in str(exc.value).lower()
