import pytest

from release_flow.config import load_config
from release_flow.exceptions import ConfigError

MINIMAL_CONFIG = """
[gitlab]
base_url = "https://gitlab.example"
token = "glpat-xxx"

[defaults]
develop_branch = "develop"
master_branch = "master"
release_branch_prefix = "release/release-"
default_bump = "patch"
freeze_commit_msg = "version freeze {version}"
bump_commit_msg = "version bump {next_version}"
merge_back_commit_msg = "Merge release {version} into develop"
mr_master_title = "Release {version}"
mr_master_body_template = "Body for {version}"

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
secondary_files = ["chart/Chart.yaml", "pipeline.yaml"]
"""


class TestLoadConfig:
    def test_loads_minimal(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.gitlab.base_url == "https://gitlab.example"
        assert cfg.gitlab.token == "glpat-xxx"
        assert cfg.defaults.develop_branch == "develop"
        assert "java" in cfg.project_types
        assert cfg.project_types["java"].primary_file == "pom.xml"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError) as exc:
            load_config(tmp_path / "missing.toml")
        assert "not found" in str(exc.value).lower()

    def test_missing_required_section_raises(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("[gitlab]\nbase_url = 'x'\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(cfg_path)

    def test_repo_override(self, tmp_path):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            MINIMAL_CONFIG + '\n[repos.my-repo]\nproject_type = "java"\nextra_secondary_files = ["custom.txt"]\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert "my-repo" in cfg.repo_overrides
        assert cfg.repo_overrides["my-repo"].extra_secondary_files == ["custom.txt"]

    def test_env_var_overrides_token(self, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(MINIMAL_CONFIG, encoding="utf-8")
        monkeypatch.setenv("GITLAB_TOKEN", "from-env")
        cfg = load_config(cfg_path)
        assert cfg.gitlab.token == "from-env"  # env wins
