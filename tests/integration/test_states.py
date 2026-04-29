"""Integration tests for build_snapshot."""

import pytest

from release_flow.git_repo import GitRepo
from release_flow.states import build_snapshot
from release_flow.version_io import FileSpec


@pytest.mark.integration
class TestBuildSnapshot:
    def test_clean_repo_with_pom(self, tmp_repo_with_origin):
        # Add pom.xml with SNAPSHOT version on develop, commit, push
        repo = tmp_repo_with_origin
        (repo / "pom.xml").write_text(
            '<project><artifactId>x</artifactId>'
            '<version>1.0.0-SNAPSHOT</version></project>',
            encoding="utf-8",
        )
        gr = GitRepo(repo)
        gr.add(["pom.xml"])
        gr.commit("add pom")
        gr.push("origin", "develop")
        primary = FileSpec(
            path=repo / "pom.xml",
            patterns=[
                r"<artifactId>[^<]+</artifactId>\s*<version>(?P<v>[^<]+)</version>"
            ],
        )
        # Fake: no GitLab MR fetched (use empty list)
        snapshot = build_snapshot(
            git=gr,
            primary=primary,
            secondaries=[],
            release_branch_prefix="release/release-",
            mrs_for_release_branch=[],
        )
        assert snapshot.current_branch == "develop"
        assert snapshot.primary_version == "1.0.0-SNAPSHOT"
        assert snapshot.working_tree_clean is True
        assert snapshot.release_branch_name is None
