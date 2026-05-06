"""Test for the `release-flow status` subcommand."""

from argparse import Namespace

import pytest

from release_flow.cli import _cmd_status


@pytest.mark.integration
class TestStatusCommand:
    def test_runs_without_error_in_java_repo(self, tmp_repo_with_origin, monkeypatch, capsys, tmp_path):
        from release_flow.git_repo import GitRepo
        from .test_flow_phases import _setup_java_repo

        _setup_java_repo(tmp_repo_with_origin)
        # Repoint origin to a parseable GitLab URL (test won't make network call to real GitLab; LIST_OPEN_MRS will fail with auth error which the impl should handle)
        gr = GitRepo(tmp_repo_with_origin)
        gr._run(["remote", "set-url", "origin", "git@gitlab.example:org/app.git"])
        monkeypatch.chdir(tmp_repo_with_origin)

        # Write a minimal config
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            '[gitlab]\nbase_url = "https://gitlab.example"\ntoken = "x"\n'
            '[defaults]\ndevelop_branch = "develop"\nmaster_branch = "master"\n'
            'release_branch_prefix = "release/release-"\ndefault_bump = "patch"\n'
            'freeze_commit_msg = "freeze {version}"\n'
            'bump_commit_msg = "bump {next_version}"\n'
            'merge_back_commit_msg = "merge"\nmr_master_title = "T"\nmr_master_body_template = "B"\n'
            '[behavior]\nconfirm_before_push = true\nconfirm_before_mr = true\n'
            'open_mr_in_browser_after_create = false\nmr_develop_strategy = "direct_push"\n'
            f'[logging]\nlog_dir = "{tmp_path / "logs"}"\nlog_retention_days = 30\nverbose_default = false\n'
            '[project_types.java]\ndetect = ["pom.xml"]\nprimary_file = "pom.xml"\n'
            'secondary_files = ["chart/Chart.yaml", "pipeline.yaml"]\n',
            encoding="utf-8",
        )

        # status command may fail due to GitLab auth — implementation should print error gracefully
        # We just assert that it returns an int (0 or 1) without throwing unhandled exception
        result = _cmd_status(Namespace(config=cfg_path, verbose=False))
        assert isinstance(result, int)
        out = capsys.readouterr().out
        # Output should mention the repo state (branch, version, phase, or "Errore")
        assert len(out) > 0
