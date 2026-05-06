"""E2E test for recovery scenarios.

The orchestrator now AUTO-HANDLES Caso A (missing SNAPSHOT bump on develop) and
Caso B (versions misaligned). These tests verify that the recovery is applied
end-to-end: files modified, commit made, push done.
"""

from pathlib import Path

import pytest

from release_flow.config import (
    BehaviorConfig,
    Config,
    DefaultsConfig,
    GitLabConfig,
    LoggingConfig,
    ProjectTypeConfig,
)
from release_flow.flow import run as flow_run
from release_flow.git_repo import GitRepo
from release_flow.gitlab_client import GitLabClient
from release_flow.prompts import ScriptedPrompter


def _make_config() -> Config:
    return Config(
        gitlab=GitLabConfig(base_url="https://gl.example", token="x"),
        defaults=DefaultsConfig(
            develop_branch="develop", master_branch="master",
            release_branch_prefix="release/release-", default_bump="patch",
            freeze_commit_msg="version freeze {version}",
            bump_commit_msg="version bump {next_version}",
            merge_back_commit_msg="Merge",
            mr_master_title="T", mr_master_body_template="B",
        ),
        behavior=BehaviorConfig(
            confirm_before_push=True, confirm_before_mr=True,
            open_mr_in_browser_after_create=False,
            mr_develop_strategy="direct_push",
        ),
        logging=LoggingConfig(log_dir="/tmp", log_retention_days=30, verbose_default=False),
        project_types={"java": ProjectTypeConfig(
            detect=["pom.xml"], primary_file="pom.xml",
            secondary_files=["chart/Chart.yaml", "pipeline.yaml"],
        )},
        repo_overrides={},
    )


def _setup_java_repo_with_version(repo: Path, primary_v: str, chart_v: str | None = None, pipeline_v: str | None = None):
    """Create java project files with explicit per-file versions."""
    chart_v = chart_v or primary_v
    pipeline_v = pipeline_v or primary_v
    (repo / "pom.xml").write_text(
        f'<project>\n  <artifactId>app</artifactId>\n  <version>{primary_v}</version>\n</project>\n',
        encoding="utf-8",
    )
    chart_dir = repo / "chart"
    chart_dir.mkdir(exist_ok=True)
    (chart_dir / "Chart.yaml").write_text(
        f"apiVersion: v2\nappVersion: {chart_v}\nname: app\nversion: {chart_v}\n",
        encoding="utf-8",
    )
    (repo / "pipeline.yaml").write_text(
        f'DEPLOY:\n  app:\n    VERSION_TO_INSTALL: "{pipeline_v}"\n',
        encoding="utf-8",
    )


@pytest.mark.integration
class TestRecoveryCasoA:
    def test_auto_recovers_missing_snapshot_bump(self, tmp_repo_with_origin, monkeypatch):
        """Caso A: develop has 1.0.0 (no -SNAPSHOT). Auto-recover bumps to 1.0.1-SNAPSHOT."""
        repo = tmp_repo_with_origin
        _setup_java_repo_with_version(repo, "1.0.0", "1.0.0", "1.0.0")
        gr = GitRepo(repo)
        gr.add(["pom.xml", "chart/Chart.yaml", "pipeline.yaml"])
        gr.commit("setup with non-SNAPSHOT (anomaly)")
        gr.push("origin", "develop")

        cfg = _make_config()
        client = GitLabClient(base_url=cfg.gitlab.base_url, token=cfg.gitlab.token)
        monkeypatch.setattr(GitLabClient, "project_path_from_url", lambda self, url: "org/app")
        monkeypatch.setattr(GitLabClient, "list_open_mrs", lambda self, *a, **kw: [])

        prompter = ScriptedPrompter()
        prompter.queue([
            "1.0.1-SNAPSHOT",  # next-snapshot version
            "yes",             # confirm bump
            "no",              # decline proceeding to release
        ])

        result = flow_run(
            repo_root=repo, config=cfg, gitlab=client,
            prompter=prompter, allow_dirty=False,
        )

        # Verify files were updated
        assert "1.0.1-SNAPSHOT" in (repo / "pom.xml").read_text(encoding="utf-8")
        assert "1.0.1-SNAPSHOT" in (repo / "chart/Chart.yaml").read_text(encoding="utf-8")
        assert "1.0.1-SNAPSHOT" in (repo / "pipeline.yaml").read_text(encoding="utf-8")
        # And committed
        assert "version bump 1.0.1-SNAPSHOT" in gr.last_commit_message()
        # User declined to proceed → exits with CLEAN
        assert result.final_phase.value == "CLEAN"


@pytest.mark.integration
class TestRecoveryCasoB:
    def test_auto_recovers_misaligned_versions(self, tmp_repo_with_origin, monkeypatch):
        """Caso B: pom 1.0.0-SNAPSHOT, Chart 0.9.0-SNAPSHOT. Auto-align to chosen version."""
        repo = tmp_repo_with_origin
        _setup_java_repo_with_version(repo, "1.0.0-SNAPSHOT", "0.9.0-SNAPSHOT", "1.0.0-SNAPSHOT")
        gr = GitRepo(repo)
        gr.add(["pom.xml", "chart/Chart.yaml", "pipeline.yaml"])
        gr.commit("setup with misaligned versions")
        gr.push("origin", "develop")

        cfg = _make_config()
        client = GitLabClient(base_url=cfg.gitlab.base_url, token=cfg.gitlab.token)
        monkeypatch.setattr(GitLabClient, "project_path_from_url", lambda self, url: "org/app")
        monkeypatch.setattr(GitLabClient, "list_open_mrs", lambda self, *a, **kw: [])

        prompter = ScriptedPrompter()
        prompter.queue([
            "1.0.0-SNAPSHOT",  # choose pom version as authoritative
            "yes",             # confirm align
            "no",              # decline proceeding to release
        ])

        result = flow_run(
            repo_root=repo, config=cfg, gitlab=client,
            prompter=prompter, allow_dirty=False,
        )

        # Verify Chart.yaml was bumped to align with pom
        chart_content = (repo / "chart/Chart.yaml").read_text(encoding="utf-8")
        assert "1.0.0-SNAPSHOT" in chart_content
        assert "0.9.0-SNAPSHOT" not in chart_content
        # And committed
        assert "align versions" in gr.last_commit_message().lower()
        # User declined to proceed → exits with CLEAN
        assert result.final_phase.value == "CLEAN"
