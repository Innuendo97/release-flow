"""End-to-end happy path test: invoke release-flow main() like a user would."""

import pytest
import responses

from release_flow.cli import main

_E2E_CONFIG = '''[gitlab]
base_url = "https://gitlab.example"
token = "glpat-xxx"

[defaults]
develop_branch = "develop"
master_branch = "master"
release_branch_prefix = "release/release-"
default_bump = "patch"
freeze_commit_msg = "version freeze {{version}}"
bump_commit_msg = "version bump {{next_version}}"
merge_back_commit_msg = "Merge release {{version}} into develop"
mr_master_title = "Release {{version}}"
mr_master_body_template = "body"

[behavior]
confirm_before_push = true
confirm_before_mr = true
open_mr_in_browser_after_create = false
mr_develop_strategy = "direct_push"

[logging]
log_dir = "{log_dir}"
log_retention_days = 30
verbose_default = false

[project_types.java]
detect = ["pom.xml"]
primary_file = "pom.xml"
secondary_files = ["chart/Chart.yaml", "pipeline.yaml"]
'''


@pytest.mark.integration
class TestE2EHappyPathCLI:
    @responses.activate
    def test_run_via_cli_main(self, tmp_repo_with_origin, monkeypatch, tmp_path):
        from release_flow.prompts import ScriptedPrompter

        from .test_flow_phases import _setup_java_repo

        _mr_item = {
            "iid": 200,
            "title": "Release 1.0.0",
            "source_branch": "release/release-1.0.0",
            "target_branch": "master",
            "state": "opened",
            "web_url": "https://gitlab.example/.../200",
            "author": {"username": "me"},
        }

        # GitLab mocks: project lookup — needed once per list_open_mrs call.
        # The orchestrator calls list_open_mrs on every iteration. Add enough
        # instances to cover all iterations safely (~20, matching test_flow_happy_path.py).
        for _ in range(20):
            responses.get(
                "https://gitlab.example/api/v4/projects/org%2Fapp",
                json={"id": 1, "path": "app"},
                status=200,
            )

        # Before MR creation: list MRs returns [].
        # Calls: iter1 (CLEAN) + iter2 (RELEASE_BRANCH_CREATED) + iter3 (FROZEN_LOCAL)
        # + iter4 top (FROZEN_PUSHED) + iter4 idempotency inside execute_phase_frozen_pushed
        # = ~5 empty calls before the POST (err on the side of more).
        for _ in range(5):
            responses.add(
                responses.GET,
                "https://gitlab.example/api/v4/projects/1/merge_requests",
                json=[],
                status=200,
            )

        # Create MR
        responses.post(
            "https://gitlab.example/api/v4/projects/1/merge_requests",
            json=_mr_item,
            status=201,
        )

        # After creation: list MRs returns the open MR for all subsequent calls
        # (MR_MASTER_OPEN + BUMP_PENDING + BUMPED_LOCAL + DONE check = several calls)
        for _ in range(10):
            responses.add(
                responses.GET,
                "https://gitlab.example/api/v4/projects/1/merge_requests",
                json=[_mr_item],
                status=200,
            )

        # Setup repo
        repo = tmp_repo_with_origin
        _setup_java_repo(repo)
        monkeypatch.chdir(repo)

        # Keep the git remote pointing at the local bare repo so that push/pull work.
        # Monkeypatch project_path_from_url so that the GitLabClient derives the
        # correct mock project path without needing a real SSH remote URL.
        monkeypatch.setattr(
            "release_flow.gitlab_client.GitLabClient.project_path_from_url",
            lambda self, url: "org/app",
        )

        # Write config — use forward slashes so the path is valid inside a TOML
        # double-quoted string on Windows (backslashes would be treated as escapes).
        cfg_path = tmp_path / "config.toml"
        log_dir_fwd = str(tmp_path / "logs").replace("\\", "/")
        cfg_path.write_text(
            _E2E_CONFIG.format(log_dir=log_dir_fwd),
            encoding="utf-8",
        )

        # Patch QuestionaryPrompter at the source module level.
        # _cmd_main does `from release_flow.prompts import QuestionaryPrompter` at
        # call time, so patching release_flow.prompts.QuestionaryPrompter ensures
        # the local binding picks up our fake.
        sp = ScriptedPrompter()
        sp.queue([
            "1.0.0", "release/release-1.0.0",          # CLEAN
            "version freeze 1.0.0",                     # RELEASE_BRANCH_CREATED
            "yes",                                      # FROZEN_LOCAL push
            "yes", "Release 1.0.0",                     # FROZEN_PUSHED: confirm MR upfront, then title
            "yes", "1.0.1-SNAPSHOT", "version bump 1.0.1-SNAPSHOT",  # BUMP_PENDING: confirm + version + msg
            "yes", "yes",                               # BUMPED_LOCAL --ours, push
        ])
        sp.queue_edit("body")
        monkeypatch.setattr("release_flow.prompts.QuestionaryPrompter", lambda: sp)

        result = main(["--config", str(cfg_path)])
        assert result == 0
        # Verify version was bumped
        assert "1.0.1-SNAPSHOT" in (repo / "pom.xml").read_text(encoding="utf-8")
