from pathlib import Path

import pytest

from release_flow.flow import (
    execute_phase_clean,
    execute_phase_frozen_local,
    execute_phase_release_branch_created,
)
from release_flow.git_repo import GitRepo
from release_flow.prompts import ScriptedPrompter
from release_flow.version_bump import BumpType
from release_flow.version_io import (
    CHART_SECONDARY_PATTERNS,
    PIPELINE_SECONDARY_PATTERN,
    FileSpec,
)


def _setup_java_repo(repo: Path) -> None:
    """Create pom.xml + chart/Chart.yaml + pipeline.yaml at 1.0.0-SNAPSHOT."""
    (repo / "pom.xml").write_text(
        '<project>\n'
        '    <artifactId>app</artifactId>\n'
        '    <version>1.0.0-SNAPSHOT</version>\n'
        '</project>\n',
        encoding="utf-8",
    )
    chart = repo / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "appVersion: 1.0.0-SNAPSHOT\n"
        "name: app\n"
        "version: 1.0.0-SNAPSHOT\n",
        encoding="utf-8",
    )
    (repo / "pipeline.yaml").write_text(
        'DEPLOY:\n'
        '  app:\n'
        '    VERSION_TO_INSTALL: "1.0.0-SNAPSHOT"\n',
        encoding="utf-8",
    )
    gr = GitRepo(repo)
    gr.add(["pom.xml", "chart/Chart.yaml", "pipeline.yaml"])
    gr.commit("add project files")
    gr.push("origin", "develop")


@pytest.mark.integration
class TestExecutePhaseClean:
    def test_creates_release_branch_and_modifies_files(self, tmp_repo_with_origin):
        repo = tmp_repo_with_origin
        _setup_java_repo(repo)
        gr = GitRepo(repo)
        primary = FileSpec(
            path=repo / "pom.xml",
            patterns=[r"<artifactId>[^<]+</artifactId>\s*<version>(?P<v>[^<]+)</version>"],
        )
        secondaries = [
            FileSpec(path=repo / "chart/Chart.yaml", patterns=CHART_SECONDARY_PATTERNS),
            FileSpec(path=repo / "pipeline.yaml", patterns=[PIPELINE_SECONDARY_PATTERN]),
        ]
        prompter = ScriptedPrompter()
        prompter.queue([
            "1.0.0",                       # release version (default = strip)
            "release/release-1.0.0",       # branch name
        ])

        execute_phase_clean(
            git=gr,
            primary=primary,
            secondaries=secondaries,
            prompter=prompter,
            current_version="1.0.0-SNAPSHOT",
            release_branch_prefix="release/release-",
            default_bump=BumpType.PATCH,
        )

        assert gr.current_branch() == "release/release-1.0.0"
        assert "1.0.0-SNAPSHOT" not in (repo / "pom.xml").read_text(encoding="utf-8")
        assert "<version>1.0.0</version>" in (repo / "pom.xml").read_text(encoding="utf-8")
        chart_content = (repo / "chart/Chart.yaml").read_text(encoding="utf-8")
        assert "appVersion: 1.0.0\n" in chart_content
        assert "version: 1.0.0\n" in chart_content
        assert 'VERSION_TO_INSTALL: "1.0.0"' in (repo / "pipeline.yaml").read_text(encoding="utf-8")
        # Files modified but NOT yet committed (we're in RELEASE_BRANCH_CREATED phase)
        assert gr.is_working_tree_clean() is False


@pytest.mark.integration
class TestExecutePhaseReleaseBranchCreated:
    def test_commits_freeze(self, tmp_repo_with_origin):
        repo = tmp_repo_with_origin
        _setup_java_repo(repo)
        gr = GitRepo(repo)
        gr.create_branch("release/release-1.0.0")
        # Modify a file to simulate state after Task 21
        (repo / "pom.xml").write_text(
            (repo / "pom.xml").read_text().replace("1.0.0-SNAPSHOT", "1.0.0"),
            encoding="utf-8",
        )
        prompter = ScriptedPrompter()
        prompter.queue([
            "version freeze 1.0.0",   # commit message default-confirmed
        ])

        execute_phase_release_branch_created(
            git=gr,
            release_version="1.0.0",
            modified_files=["pom.xml"],
            prompter=prompter,
            commit_msg_template="version freeze {version}",
        )
        assert "version freeze 1.0.0" in gr.last_commit_message()
        assert gr.is_working_tree_clean() is True


@pytest.mark.integration
class TestExecutePhaseFrozenLocal:
    def test_pull_master_and_push(self, tmp_repo_with_origin):
        repo = tmp_repo_with_origin
        _setup_java_repo(repo)
        gr = GitRepo(repo)
        gr.create_branch("release/release-1.0.0")
        (repo / "pom.xml").write_text(
            (repo / "pom.xml").read_text().replace("1.0.0-SNAPSHOT", "1.0.0"),
            encoding="utf-8",
        )
        gr.add(["pom.xml"])
        gr.commit("version freeze 1.0.0")
        prompter = ScriptedPrompter()
        prompter.queue(["yes"])  # confirm push

        execute_phase_frozen_local(
            git=gr,
            release_branch="release/release-1.0.0",
            master_branch="master",
            prompter=prompter,
            confirm_before_push=True,
        )
        # branch is pushed
        assert "origin/release/release-1.0.0" in gr.remote_branches()
