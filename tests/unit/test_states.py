from pathlib import Path

from release_flow.gitlab_client import MergeRequest
from release_flow.states import Phase, RepoSnapshot, detect_phase


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


def _snapshot(**overrides) -> RepoSnapshot:
    """Build a snapshot with sensible defaults; override fields per test."""
    base = dict(
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
    base.update(overrides)
    return RepoSnapshot(**base)


class TestDetectPhase:
    def test_clean_phase(self):
        s = _snapshot()
        assert detect_phase(s) == Phase.CLEAN

    def test_release_branch_created(self):
        s = _snapshot(
            current_branch="release/release-1.1.27",
            release_branch_name="release/release-1.1.27",
            primary_version="1.1.27",  # already stripped
            working_tree_clean=False,  # files modified, not yet committed
            local_branches=["develop", "master", "release/release-1.1.27"],
            last_commit_message="some old commit",  # no freeze yet
        )
        assert detect_phase(s) == Phase.RELEASE_BRANCH_CREATED

    def test_frozen_local(self):
        s = _snapshot(
            current_branch="release/release-1.1.27",
            release_branch_name="release/release-1.1.27",
            primary_version="1.1.27",
            working_tree_clean=True,
            local_branches=["develop", "master", "release/release-1.1.27"],
            remote_branches=["origin/develop", "origin/master"],  # NOT pushed yet
            last_commit_message="version freeze 1.1.27",
        )
        assert detect_phase(s) == Phase.FROZEN_LOCAL

    def test_frozen_pushed(self):
        s = _snapshot(
            current_branch="release/release-1.1.27",
            release_branch_name="release/release-1.1.27",
            primary_version="1.1.27",
            working_tree_clean=True,
            local_branches=["develop", "master", "release/release-1.1.27"],
            remote_branches=[
                "origin/develop", "origin/master",
                "origin/release/release-1.1.27",  # pushed
            ],
            last_commit_message="version freeze 1.1.27",
            open_mrs_for_release_branch=[],  # MR not yet
        )
        assert detect_phase(s) == Phase.FROZEN_PUSHED

    def test_mr_master_open(self):
        s = _snapshot(
            current_branch="release/release-1.1.27",
            release_branch_name="release/release-1.1.27",
            primary_version="1.1.27",
            working_tree_clean=True,
            remote_branches=[
                "origin/develop", "origin/master",
                "origin/release/release-1.1.27",
            ],
            last_commit_message="version freeze 1.1.27",
            open_mrs_for_release_branch=[
                MergeRequest(
                    iid=142, title="Release 1.1.27",
                    source_branch="release/release-1.1.27",
                    target_branch="master",
                    state="opened",
                    web_url="https://x", author_username="me",
                ),
            ],
        )
        assert detect_phase(s) == Phase.MR_MASTER_OPEN

    def test_bump_pending(self):
        s = _snapshot(
            current_branch="develop",
            primary_version="1.1.27-SNAPSHOT",  # still old SNAPSHOT
            working_tree_clean=True,
            local_branches=["develop", "master", "release/release-1.1.27"],
            remote_branches=[
                "origin/develop", "origin/master",
                "origin/release/release-1.1.27",
            ],
            last_commit_message="some old commit",
            open_mrs_for_release_branch=[
                MergeRequest(
                    iid=142, title="Release 1.1.27",
                    source_branch="release/release-1.1.27",
                    target_branch="master", state="opened",
                    web_url="https://x", author_username="me",
                ),
            ],
        )
        assert detect_phase(s) == Phase.BUMP_PENDING

    def test_bumped_local(self):
        s = _snapshot(
            current_branch="develop",
            primary_version="1.1.28-SNAPSHOT",  # next snapshot, set
            working_tree_clean=True,
            last_commit_message="version bump 1.1.28-SNAPSHOT",
            local_branches=["develop", "master", "release/release-1.1.27"],
            remote_branches=[
                "origin/develop", "origin/master",
                "origin/release/release-1.1.27",
            ],
            develop_ahead_of_origin=True,  # pre-merge-back
        )
        assert detect_phase(s) == Phase.BUMPED_LOCAL

    def test_done(self):
        s = _snapshot(
            current_branch="develop",
            primary_version="1.1.28-SNAPSHOT",
            working_tree_clean=True,
            last_commit_message="Merge release 1.1.27 into develop",
            local_branches=["develop", "master"],
            remote_branches=["origin/develop", "origin/master"],
            develop_ahead_of_origin=False,
        )
        assert detect_phase(s) == Phase.DONE
