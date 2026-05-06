"""Unit tests for flow orchestrator (pre-flight checks)."""

from pathlib import Path

from release_flow.flow import evaluate_branch_policy, run_preflight
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


class TestPreflight:
    def test_clean_passes(self):
        s = _snapshot()
        result = run_preflight(s, allow_dirty=False)
        assert result.passed is True

    def test_dirty_tree_fails(self):
        s = _snapshot(working_tree_clean=False)
        result = run_preflight(s, allow_dirty=False)
        assert result.passed is False
        assert any("working tree" in r.lower() for r in result.failures)

    def test_dirty_tree_with_allow_dirty_passes(self):
        s = _snapshot(working_tree_clean=False)
        result = run_preflight(s, allow_dirty=True)
        assert result.passed is True

    def test_missing_master_branch_fails(self):
        s = _snapshot(remote_branches=["origin/develop"])
        result = run_preflight(s, allow_dirty=False)
        assert result.passed is False
        assert any("master" in r.lower() for r in result.failures)

    def test_inconsistent_versions_fails(self):
        s = _snapshot(secondary_versions_consistent=False)
        result = run_preflight(s, allow_dirty=False)
        assert result.passed is False
        assert any("version" in r.lower() for r in result.failures)


class TestBranchPolicy:
    def test_on_develop_proceeds(self):
        s = _snapshot(current_branch="develop")
        r = evaluate_branch_policy(s)
        assert r.action == "proceed"

    def test_on_release_branch_resumes(self):
        s = _snapshot(
            current_branch="release/release-1.0.0",
            release_branch_name="release/release-1.0.0",
        )
        r = evaluate_branch_policy(s)
        assert r.action == "resume"

    def test_on_feature_branch_with_no_unmerged_commits(self):
        # When feature branch has no unique commits, can switch to develop
        s = _snapshot(
            current_branch="feature/x",
            local_branches=["develop", "master", "feature/x"],
        )
        r = evaluate_branch_policy(s, feature_has_unmerged_commits=False)
        assert r.action == "switch_to_develop"

    def test_on_feature_branch_with_unmerged_commits(self):
        s = _snapshot(
            current_branch="feature/x",
            local_branches=["develop", "master", "feature/x"],
        )
        r = evaluate_branch_policy(s, feature_has_unmerged_commits=True)
        assert r.action == "stop"
        assert "merge" in r.reason.lower()


class TestFindOrphanReleaseBranch:
    """Detect release branches that exist on origin but have no open MR
    (typical case: user previously declined to create the MR, now wants
    to create it without starting a new release)."""

    def _fake_git(self, remote_branches):
        from unittest.mock import MagicMock
        git = MagicMock()
        git.remote_branches.return_value = remote_branches
        return git

    def test_returns_none_when_no_release_branches(self):
        from release_flow.flow import _find_orphan_release_branch
        git = self._fake_git(["origin/develop", "origin/master"])
        assert _find_orphan_release_branch(git, [], "release/release-") is None

    def test_returns_none_when_release_has_open_mr(self):
        from release_flow.flow import _find_orphan_release_branch
        from release_flow.gitlab_client import MergeRequest

        git = self._fake_git([
            "origin/develop", "origin/master",
            "origin/release/release-1.0.0",
        ])
        mrs = [
            MergeRequest(
                iid=1, title="x", source_branch="release/release-1.0.0",
                target_branch="master", state="opened",
                web_url="https://x", author_username="me",
            ),
        ]
        assert _find_orphan_release_branch(git, mrs, "release/release-") is None

    def test_returns_orphan_branch(self):
        from release_flow.flow import _find_orphan_release_branch
        git = self._fake_git([
            "origin/develop", "origin/master",
            "origin/release/release-1.1.14",
        ])
        # No MRs at all → branch is orphan
        result = _find_orphan_release_branch(git, [], "release/release-")
        assert result == "release/release-1.1.14"

    def test_returns_most_recent_when_multiple_orphans(self):
        from release_flow.flow import _find_orphan_release_branch
        git = self._fake_git([
            "origin/develop", "origin/master",
            "origin/release/release-1.0.0",
            "origin/release/release-1.1.14",
            "origin/release/release-1.0.5",
        ])
        result = _find_orphan_release_branch(git, [], "release/release-")
        # Lexicographic sort puts 1.1.14 last
        assert result == "release/release-1.1.14"
