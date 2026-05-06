"""Config loader for ~/.config/release-flow/config.toml.

Layered: file values < environment variables < CLI flags (CLI applied later in cli.py).
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from release_flow.exceptions import ConfigError


@dataclass(frozen=True)
class GitLabConfig:
    base_url: str
    token: str
    http_timeout_seconds: int = 30


@dataclass(frozen=True)
class DefaultsConfig:
    develop_branch: str
    master_branch: str
    release_branch_prefix: str
    default_bump: str
    freeze_commit_msg: str
    bump_commit_msg: str
    merge_back_commit_msg: str
    mr_master_title: str
    mr_master_body_template: str


@dataclass(frozen=True)
class BehaviorConfig:
    confirm_before_push: bool = True
    confirm_before_mr: bool = True
    confirm_before_bump: bool = True
    open_mr_in_browser_after_create: bool = True
    editor: str = ""
    mr_develop_strategy: str = "direct_push"


@dataclass(frozen=True)
class LoggingConfig:
    log_dir: str
    log_retention_days: int = 30
    verbose_default: bool = False


@dataclass(frozen=True)
class ProjectTypeConfig:
    detect: list[str]
    primary_file: str
    secondary_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepoOverride:
    project_type: str | None = None
    extra_secondary_files: list[str] = field(default_factory=list)
    custom_patterns: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Config:
    gitlab: GitLabConfig
    defaults: DefaultsConfig
    behavior: BehaviorConfig
    logging: LoggingConfig
    project_types: dict[str, ProjectTypeConfig]
    repo_overrides: dict[str, RepoOverride]


REQUIRED_SECTIONS = ["gitlab", "defaults", "behavior", "logging"]


def load_config(path: Path) -> Config:
    """Load and validate config from a TOML file. Apply env-var overrides."""
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"malformed TOML in {path}: {e}") from e

    for section in REQUIRED_SECTIONS:
        if section not in raw:
            raise ConfigError(f"missing required section [{section}] in {path}")

    gitlab_raw = raw["gitlab"]
    token = os.environ.get("GITLAB_TOKEN") or gitlab_raw.get("token", "")
    if not token:
        raise ConfigError("no GitLab token: set [gitlab].token in config or env GITLAB_TOKEN")
    gitlab = GitLabConfig(
        base_url=gitlab_raw["base_url"],
        token=token,
        http_timeout_seconds=gitlab_raw.get("http_timeout_seconds", 30),
    )

    defaults = DefaultsConfig(**raw["defaults"])
    behavior = BehaviorConfig(**raw["behavior"])
    logging_cfg = LoggingConfig(**raw["logging"])

    project_types_raw = raw.get("project_types", {})
    project_types = {
        name: ProjectTypeConfig(**spec) for name, spec in project_types_raw.items()
    }

    repos_raw = raw.get("repos", {})
    repo_overrides = {
        name: RepoOverride(**spec) for name, spec in repos_raw.items()
    }

    return Config(
        gitlab=gitlab,
        defaults=defaults,
        behavior=behavior,
        logging=logging_cfg,
        project_types=project_types,
        repo_overrides=repo_overrides,
    )


def default_config_path() -> Path:
    """Return platform-appropriate config path."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "release-flow" / "config.toml"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "release-flow" / "config.toml"
