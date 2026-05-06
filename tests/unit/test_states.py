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

    def test_frozen_local_after_master_merge(self):
        """Real-world scenario: user did `git pull origin master` after the
        freeze commit, creating a merge commit on top. Phase should still be
        FROZEN_LOCAL because the version is non-SNAPSHOT (= frozen)."""
        s = _snapshot(
            current_branch="release/release-1.1.16",
            release_branch_name="release/release-1.1.16",
            primary_version="1.1.16",  # non-SNAPSHOT = frozen
            working_tree_clean=True,
            local_branches=["develop", "master", "release/release-1.1.16"],
            remote_branches=["origin/develop", "origin/master"],  # NOT pushed
            last_commit_message="Merge branch 'master' into release/release-1.1.16",
        )
        assert detect_phase(s) == Phase.FROZEN_LOCAL

    def test_release_branch_clean_but_snapshot_still_present(self):
        """Edge case: release branch created but freeze step not done yet.
        Working tree clean, but version is still SNAPSHOT → RELEASE_BRANCH_CREATED."""
        s = _snapshot(
            current_branch="release/release-1.1.16",
            release_branch_name="release/release-1.1.16",
            primary_version="1.1.16-SNAPSHOT",  # still SNAPSHOT
            working_tree_clean=True,
            local_branches=["develop", "master", "release/release-1.1.16"],
            remote_branches=["origin/develop", "origin/master"],
            last_commit_message="some random commit",
        )
        assert detect_phase(s) == Phase.RELEASE_BRANCH_CREATED

    def test_recovery_then_release_needs_merge_back(self):
        """Real scenario: Caso A recovery bumped develop to 1.1.17-SNAPSHOT
        BEFORE the release of 1.1.16 was cut. After MR creation, we're on
        develop with version already-bumped. Need to detect BUMPED_LOCAL
        (not BUMP_PENDING) so merge-back is the next action."""
        s = _snapshot(
            current_branch="develop",
            primary_version="1.1.17-SNAPSHOT",  # bumped during recovery
            working_tree_clean=True,
            last_commit_message="version bump 1.1.17-SNAPSHOT",
            local_branches=["develop", "master", "release/release-1.1.16"],
            remote_branches=[
                "origin/develop", "origin/master",
                "origin/release/release-1.1.16",
            ],
            open_mrs_for_release_branch=[
                MergeRequest(
                    iid=300, title="Release 1.1.16",
                    source_branch="release/release-1.1.16",
                    target_branch="master", state="opened",
                    web_url="https://x", author_username="me",
                ),
            ],
            develop_ahead_of_origin=False,  # already pushed during recovery
            release_branches_pending_merge_back=["release/release-1.1.16"],
            bump_already_done=True,  # 1.1.17 > 1.1.16
        )
        assert detect_phase(s) == Phase.BUMPED_LOCAL

    def test_recovery_then_release_after_merge_back_done(self):
        """Same scenario as above but merge-back already done. Should be DONE."""
        s = _snapshot(
            current_branch="develop",
            primary_version="1.1.17-SNAPSHOT",
            working_tree_clean=True,
            last_commit_message="Merge release 1.1.16 into develop",
            local_branches=["develop", "master", "release/release-1.1.16"],
            remote_branches=[
                "origin/develop", "origin/master",
                "origin/release/release-1.1.16",
            ],
            open_mrs_for_release_branch=[
                MergeRequest(
                    iid=300, title="Release 1.1.16",
                    source_branch="release/release-1.1.16",
                    target_branch="master", state="opened",
                    web_url="https://x", author_username="me",
                ),
            ],
            develop_ahead_of_origin=False,
            release_branches_pending_merge_back=[],  # merge-back done
            bump_already_done=True,
        )
        assert detect_phase(s) == Phase.DONE
