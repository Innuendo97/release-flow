from pathlib import Path

from release_flow.states import Phase, RepoSnapshot


class TestRepoSnapshot:
    def test_phase_enum_exists(self):
        """Verify Phase enum is importable."""
        assert Phase.CLEAN == "CLEAN"

    def test_construction(self):
        s = RepoSnapshot(
            repo_root=Path("/tmp/x"),
            current_branch="develop",
            working_tree_clean=True,
            primary_version="1.1.27-SNAPSHOT",
            secondary_versions_consistent=True,
            last_commit_message="some commit",
            local_branches=["develop", "master"],
            remote_branches=["origin/develop", "origin/master"],
            open_mrs_for_release_branch=[],
            release_branch_name=None,
        )
        assert s.current_branch == "develop"
        assert s.is_on_develop is True
        assert s.is_on_release_branch is False

    def test_is_on_release_branch(self):
        s = RepoSnapshot(
            repo_root=Path("/tmp/x"),
            current_branch="release/release-1.0.0",
            working_tree_clean=True,
            primary_version="1.0.0",
            secondary_versions_consistent=True,
            last_commit_message="version freeze 1.0.0",
            local_branches=["develop", "master", "release/release-1.0.0"],
            remote_branches=["origin/develop", "origin/master"],
            open_mrs_for_release_branch=[],
            release_branch_name="release/release-1.0.0",
        )
        assert s.is_on_release_branch is True
        assert s.is_on_develop is False
