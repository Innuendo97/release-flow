import pytest

from release_flow.git_repo import GitRepo


@pytest.mark.integration
class TestGitRepoReadOps:
    def test_is_git_repo(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        assert gr.is_git_repo() is True

    def test_is_not_git_repo(self, tmp_path):
        gr = GitRepo(tmp_path)
        assert gr.is_git_repo() is False

    def test_current_branch(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        assert gr.current_branch() == "main"

    def test_working_tree_clean(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        assert gr.is_working_tree_clean() is True

    def test_working_tree_dirty(self, tmp_git_repo):
        (tmp_git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
        gr = GitRepo(tmp_git_repo)
        assert gr.is_working_tree_clean() is False

    def test_last_commit_message(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        assert "initial" in gr.last_commit_message()

    def test_local_branches(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        branches = gr.local_branches()
        assert "main" in branches
        assert "develop" in branches
        assert "master" in branches

    def test_remote_branches(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        branches = gr.remote_branches("origin")
        assert "origin/main" in branches
        assert "origin/develop" in branches
        assert "origin/master" in branches

    def test_remote_url(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        url = gr.remote_url("origin")
        assert "origin.git" in url


@pytest.mark.integration
class TestGitRepoWriteOps:
    def test_create_branch(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        gr.create_branch("feature/x")
        assert gr.current_branch() == "feature/x"

    def test_checkout(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        gr.checkout("master")
        assert gr.current_branch() == "master"

    def test_commit(self, tmp_git_repo):
        (tmp_git_repo / "x.txt").write_text("hello", encoding="utf-8")
        gr = GitRepo(tmp_git_repo)
        gr.add(["x.txt"])
        gr.commit("test commit")
        assert "test commit" in gr.last_commit_message()

    def test_push_normal(self, tmp_repo_with_origin):
        # Add a commit on develop and push
        (tmp_repo_with_origin / "x.txt").write_text("hello", encoding="utf-8")
        gr = GitRepo(tmp_repo_with_origin)
        gr.add(["x.txt"])
        gr.commit("add x")
        gr.push("origin", "develop")  # normal (non-force) push to develop is allowed
        # branches still exist
        assert "develop" in gr.local_branches()

    def test_pull_ff_only(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        gr.pull_ff_only("origin", "develop")  # should not raise on up-to-date

    def test_delete_release_branch(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        gr.create_branch("release/release-1.0.0")
        gr.checkout("develop")
        gr.delete_local_branch("release/release-1.0.0")
        assert "release/release-1.0.0" not in gr.local_branches()


@pytest.mark.integration
class TestLastMeaningfulCommitMessage:
    def test_skips_version_freeze_and_bump(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        (tmp_git_repo / "feature.txt").write_text("change", encoding="utf-8")
        gr.add(["feature.txt"])
        gr.commit("fix: real user change")
        (tmp_git_repo / "x.txt").write_text("v", encoding="utf-8")
        gr.add(["x.txt"])
        gr.commit("version bump 1.2.0-SNAPSHOT")
        (tmp_git_repo / "y.txt").write_text("v", encoding="utf-8")
        gr.add(["y.txt"])
        gr.commit("version freeze 1.2.0")
        # Should skip the two version-* commits and return the real one
        assert gr.last_meaningful_commit_message() == "fix: real user change"

    def test_skips_merge_commits(self, tmp_repo_with_origin):
        gr = GitRepo(tmp_repo_with_origin)
        (tmp_repo_with_origin / "feat.txt").write_text("x", encoding="utf-8")
        gr.add(["feat.txt"])
        gr.commit("feat: new endpoint")
        gr.create_branch("side")
        (tmp_repo_with_origin / "side.txt").write_text("s", encoding="utf-8")
        gr.add(["side.txt"])
        gr.commit("side: change on side branch")
        gr.checkout("develop")
        gr._run(["merge", "--no-ff", "side", "-m", "Merge branch 'side' into develop"])
        # The most recent commit is the merge — should be skipped
        msg = gr.last_meaningful_commit_message()
        assert msg == "side: change on side branch"

    def test_returns_initial_when_only_init_commit(self, tmp_git_repo):
        gr = GitRepo(tmp_git_repo)
        # Only the initial commit — should be returned (not version-*, not Merge)
        assert gr.last_meaningful_commit_message() == "initial"
