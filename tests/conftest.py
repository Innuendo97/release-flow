"""Shared test fixtures for release-flow."""

import subprocess
from pathlib import Path

import pytest


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create an empty git repo in tmp_path with one initial commit on `main`."""
    _run(["git", "init", "-b", "main"], tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], tmp_path)
    _run(["git", "config", "user.name", "Test User"], tmp_path)
    (tmp_path / "README.md").write_text("# test\n", encoding="utf-8")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-m", "initial"], tmp_path)
    return tmp_path


@pytest.fixture
def tmp_repo_with_origin(tmp_path: Path) -> Path:
    """Repo with a bare `origin` remote, so push/pull work for tests."""
    bare = tmp_path / "origin.git"
    _run(["git", "init", "--bare", "-b", "main", str(bare)], tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    _run(["git", "init", "-b", "main"], work)
    _run(["git", "config", "user.email", "test@example.com"], work)
    _run(["git", "config", "user.name", "Test User"], work)
    _run(["git", "remote", "add", "origin", str(bare)], work)
    (work / "README.md").write_text("# test\n", encoding="utf-8")
    _run(["git", "add", "."], work)
    _run(["git", "commit", "-m", "initial"], work)
    _run(["git", "checkout", "-b", "develop"], work)
    _run(["git", "push", "-u", "origin", "main", "develop"], work)
    # also create master from main
    _run(["git", "checkout", "-b", "master", "main"], work)
    _run(["git", "push", "-u", "origin", "master"], work)
    _run(["git", "checkout", "develop"], work)
    return work
