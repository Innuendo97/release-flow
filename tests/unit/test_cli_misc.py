"""Tests for doctor, abort, config-edit, logs subcommands."""

from argparse import Namespace

import responses

from release_flow.cli import _cmd_abort, _cmd_config_edit, _cmd_doctor, _cmd_logs

_MINIMAL_CONFIG_TEXT = '''[gitlab]
base_url = "https://gitlab.example"
token = "glpat-xxx"
http_timeout_seconds = 30

[defaults]
develop_branch = "develop"
master_branch = "master"
release_branch_prefix = "release/release-"
default_bump = "patch"
freeze_commit_msg = "version freeze {version}"
bump_commit_msg = "version bump {next_version}"
merge_back_commit_msg = "merge"
mr_master_title = "title"
mr_master_body_template = "body"

[behavior]
confirm_before_push = true
confirm_before_mr = true
open_mr_in_browser_after_create = false
mr_develop_strategy = "direct_push"

[logging]
log_dir = "/tmp/logs"
log_retention_days = 30
verbose_default = false

[project_types.java]
detect = ["pom.xml"]
primary_file = "pom.xml"
secondary_files = []
'''


class TestDoctor:
    @responses.activate
    def test_token_valid(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(_MINIMAL_CONFIG_TEXT, encoding="utf-8")
        responses.get(
            "https://gitlab.example/api/v4/user",
            json={"username": "me"},
            status=200,
        )
        result = _cmd_doctor(Namespace(config=cfg))
        assert result == 0


class TestAbort:
    def test_no_release_branch_returns_zero(self, tmp_repo_with_origin, monkeypatch, tmp_path):
        # Default: on develop, no release branch — abort prints "nothing to do" and exits 0
        monkeypatch.chdir(tmp_repo_with_origin)
        cfg = tmp_path / "config.toml"
        cfg.write_text(_MINIMAL_CONFIG_TEXT, encoding="utf-8")
        result = _cmd_abort(Namespace(config=cfg))
        assert result == 0


class TestLogs:
    def test_prints_log_dir(self, tmp_path, capsys):
        cfg = tmp_path / "config.toml"
        cfg.write_text(_MINIMAL_CONFIG_TEXT, encoding="utf-8")
        result = _cmd_logs(Namespace(config=cfg))
        assert result == 0
        out = capsys.readouterr().out
        assert "Log directory" in out or "log" in out.lower()


class TestConfigEdit:
    def test_missing_config_returns_one(self, tmp_path):
        # config-edit on missing config should return 1 with helpful message
        cfg = tmp_path / "missing.toml"
        result = _cmd_config_edit(Namespace(config=cfg))
        assert result == 1
