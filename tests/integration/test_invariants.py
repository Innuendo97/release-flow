import pytest

from release_flow.exceptions import ProtectedBranchError
from release_flow.git_repo import PROTECTED_BRANCH_NAMES, GitRepo


@pytest.mark.invariant
class TestProtectedBranchInvariants:
    """These tests MUST pass. They guarantee that release-flow can never
    delete or destructively modify develop/master branches. CI must block
    merge if any of these fail.
    """

    def test_PROTECTED_constant_includes_critical_names(self):  # noqa: N802
        # belt + suspenders: even if config is corrupted, these are blacklisted
        assert "develop" in PROTECTED_BRANCH_NAMES
        assert "master" in PROTECTED_BRANCH_NAMES
        assert "main" in PROTECTED_BRANCH_NAMES

    def test_cannot_delete_develop_local(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.delete_local_branch("develop")

    def test_cannot_delete_master_local(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.delete_local_branch("master")

    def test_cannot_delete_main_local(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.delete_local_branch("main")

    def test_cannot_delete_develop_remote(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.delete_remote_branch("origin", "develop")

    def test_cannot_delete_master_remote(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.delete_remote_branch("origin", "master")

    def test_cannot_force_push_develop(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.force_push("origin", "develop")

    def test_cannot_force_push_master(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.force_push("origin", "master")

    def test_cannot_hard_reset_develop(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.hard_reset_to("develop", "HEAD~1")

    def test_cannot_hard_reset_master(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        with pytest.raises(ProtectedBranchError):
            gr.hard_reset_to("master", "HEAD~1")

    def test_release_branch_can_be_deleted(self, tmp_repo_with_origin):
        # Sanity: NON-protected branches CAN be deleted normally
        gr = GitRepo(tmp_repo_with_origin)
        gr.create_branch("release/release-1.0.0")
        gr.checkout("master")
        gr.delete_local_branch("release/release-1.0.0")  # should not raise
        assert "release/release-1.0.0" not in gr.local_branches()
