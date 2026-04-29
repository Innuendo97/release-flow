"""Wrapper around python-gitlab with our error mapping."""

import re
from dataclasses import dataclass
from typing import Any

import gitlab
from gitlab.exceptions import GitlabAuthenticationError, GitlabHttpError

from release_flow.exceptions import GitLabError


@dataclass(frozen=True)
class MergeRequest:
    """Represents a GitLab merge request."""

    iid: int
    title: str
    source_branch: str
    target_branch: str
    state: str
    web_url: str
    author_username: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MergeRequest":
        """Create MergeRequest from API response dict."""
        return cls(
            iid=d["iid"],
            title=d["title"],
            source_branch=d["source_branch"],
            target_branch=d["target_branch"],
            state=d["state"],
            web_url=d["web_url"],
            author_username=d.get("author", {}).get("username", ""),
        )


SSH_RE = re.compile(r"^[^@]+@[^:]+:(?P<path>.+?)(?:\.git)?/?$")
HTTPS_RE = re.compile(r"^https?://[^/]+/(?P<path>.+?)(?:\.git)?/?$")


class GitLabClient:
    """GitLab API client wrapper with error handling."""

    def __init__(self, base_url: str, token: str, timeout: int = 30):
        """Initialize GitLabClient.

        Args:
            base_url: GitLab instance base URL (e.g., 'https://gitlab.com')
            token: GitLab personal access token (PAT)
            timeout: Request timeout in seconds (default: 30)
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._gl: gitlab.Gitlab | None = None

    def _client(self) -> gitlab.Gitlab:
        """Get or create the python-gitlab Gitlab client."""
        if self._gl is None:
            self._gl = gitlab.Gitlab(
                url=self.base_url, private_token=self.token, timeout=self.timeout
            )
        return self._gl

    @staticmethod
    def parse_remote_url(url: str) -> tuple[str, str]:
        """Parse a git remote URL to extract namespace and repo name.

        Supports SSH (`git@host:org/repo.git`) and HTTPS forms.

        Args:
            url: Git remote URL

        Returns:
            Tuple of (namespace, repo_name) where namespace may include subgroups

        Raises:
            GitLabError: If URL cannot be parsed
        """
        url = url.strip().rstrip("/")
        m = SSH_RE.match(url) or HTTPS_RE.match(url)
        if not m:
            raise GitLabError(f"cannot parse GitLab URL: {url!r}")
        path = m.group("path")
        if path.endswith(".git"):
            path = path[:-4]
        if "/" not in path:
            raise GitLabError(f"URL has no namespace: {url!r}")
        ns, _, repo = path.rpartition("/")
        return ns, repo

    def project_path_from_url(self, url: str) -> str:
        """Return 'namespace/repo' for python-gitlab project lookup.

        Args:
            url: Git remote URL

        Returns:
            Project path in 'namespace/repo' format
        """
        ns, repo = self.parse_remote_url(url)
        return f"{ns}/{repo}"

    def list_open_mrs(
        self, project_path: str, source_branch: str | None = None
    ) -> list[MergeRequest]:
        """List open merge requests for a project.

        Args:
            project_path: Project path (e.g., 'namespace/repo')
            source_branch: Optional filter by source branch

        Returns:
            List of MergeRequest objects

        Raises:
            GitLabError: On authentication or API errors
        """
        try:
            project = self._client().projects.get(project_path)
            params: dict[str, Any] = {"state": "opened"}
            if source_branch:
                params["source_branch"] = source_branch
            mrs = project.mergerequests.list(**params, all=True)
            return [MergeRequest.from_dict(mr.attributes) for mr in mrs]
        except GitlabAuthenticationError as e:
            raise GitLabError(f"PAT invalid or missing 'api' scope: {e}") from e
        except GitlabHttpError as e:
            raise GitLabError(f"GitLab API error: {e}") from e

    def create_mr(
        self,
        project_path: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> MergeRequest:
        """Create a new merge request.

        Args:
            project_path: Project path (e.g., 'namespace/repo')
            source_branch: Source branch name
            target_branch: Target branch name
            title: MR title
            description: MR description

        Returns:
            The created MergeRequest object

        Raises:
            GitLabError: On authentication or API errors
        """
        try:
            project = self._client().projects.get(project_path)
            mr = project.mergerequests.create(
                {
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "title": title,
                    "description": description,
                }
            )
            return MergeRequest.from_dict(mr.attributes)
        except GitlabAuthenticationError as e:
            raise GitLabError(f"PAT invalid (401): {e}") from e
        except GitlabHttpError as e:
            raise GitLabError(f"GitLab API error: {e}") from e
