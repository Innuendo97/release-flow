"""Tests for GitLabClient using responses HTTP mocks."""

import pytest
import responses

from release_flow.exceptions import GitLabError
from release_flow.gitlab_client import GitLabClient


@pytest.fixture
def gl_client():
    return GitLabClient(base_url="https://gitlab.example", token="glpat-xxx")


class TestProjectFromRemoteUrl:
    def test_extracts_namespace_and_repo_from_ssh(self, gl_client):
        ns, repo = gl_client.parse_remote_url("git@gitlab.example:org/sub/myrepo.git")
        assert ns == "org/sub"
        assert repo == "myrepo"

    def test_extracts_from_https(self, gl_client):
        ns, repo = gl_client.parse_remote_url("https://gitlab.example/org/sub/myrepo.git")
        assert ns == "org/sub"
        assert repo == "myrepo"

    def test_strips_trailing_slash(self, gl_client):
        _, repo = gl_client.parse_remote_url("https://gitlab.example/org/repo/")
        assert repo == "repo"


class TestListOpenMrs:
    @responses.activate
    def test_returns_open_mrs(self, gl_client):
        # Mock the project lookup call
        responses.get(
            "https://gitlab.example/api/v4/projects/org%2Frepo",
            json={"id": 1, "path": "repo"},
            status=200,
        )
        # Mock the merge_requests list call using project ID
        responses.get(
            "https://gitlab.example/api/v4/projects/1/merge_requests",
            json=[
                {
                    "iid": 142,
                    "title": "Release 1.0.0",
                    "source_branch": "release/release-1.0.0",
                    "target_branch": "master",
                    "state": "opened",
                    "web_url": "https://gitlab.example/org/repo/-/merge_requests/142",
                    "author": {"username": "test-user"},
                }
            ],
            status=200,
        )
        mrs = gl_client.list_open_mrs("org/repo", source_branch="release/release-1.0.0")
        assert len(mrs) == 1
        assert mrs[0].iid == 142
        assert mrs[0].source_branch == "release/release-1.0.0"


class TestCreateMr:
    @responses.activate
    def test_creates_mr(self, gl_client):
        # Mock the project lookup call
        responses.get(
            "https://gitlab.example/api/v4/projects/org%2Frepo",
            json={"id": 1, "path": "repo"},
            status=200,
        )
        # Mock the merge_request creation call using project ID
        responses.post(
            "https://gitlab.example/api/v4/projects/1/merge_requests",
            json={
                "iid": 143,
                "title": "Release 1.0.0",
                "source_branch": "release/release-1.0.0",
                "target_branch": "master",
                "state": "opened",
                "web_url": "https://gitlab.example/org/repo/-/merge_requests/143",
                "author": {"username": "test-user"},
            },
            status=201,
        )
        mr = gl_client.create_mr(
            project_path="org/repo",
            source_branch="release/release-1.0.0",
            target_branch="master",
            title="Release 1.0.0",
            description="body",
        )
        assert mr.iid == 143

    @responses.activate
    def test_401_raises_gitlab_error(self, gl_client):
        # Mock the project lookup call with 401 error
        responses.get(
            "https://gitlab.example/api/v4/projects/org%2Frepo",
            json={"message": "401 Unauthorized"},
            status=401,
        )
        with pytest.raises(GitLabError) as exc:
            gl_client.create_mr(
                project_path="org/repo",
                source_branch="x",
                target_branch="master",
                title="t",
                description="b",
            )
        assert "PAT" in str(exc.value) or "401" in str(exc.value)
