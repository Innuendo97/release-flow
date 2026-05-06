"""End-to-end idempotency test: rerun after DONE is a no-op."""

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
class TestIdempotency:
    @responses.activate
    def test_rerun_after_done_is_noop(self, tmp_repo_with_origin, monkeypatch, tmp_path):
        from release_flow.gitlab_client import GitLabClient
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

        # Mock project lookup — used on every list_open_mrs call (once per iteration).
        # Provide enough for both first and second runs (~40 total to be safe).
        for _ in range(40):
            responses.get(
                "https://gitlab.example/api/v4/projects/org%2Fapp",
                json={"id": 1, "path": "app"},
                status=200,
            )

        # Before MR creation: list MRs returns [].
        # Calls during first run: iter1 (CLEAN) + iter2 (RELEASE_BRANCH_CREATED)
        # + iter3 (FROZEN_LOCAL) + iter4 top (FROZEN_PUSHED) + idempotency check inside
        # execute_phase_frozen_pushed = ~5 empty calls before the POST.
        for _ in range(5):
            responses.add(
                responses.GET,
                "https://gitlab.example/api/v4/projects/1/merge_requests",
                json=[],
                status=200,
            )

        # Create MR (first run only)
        responses.post(
            "https://gitlab.example/api/v4/projects/1/merge_requests",
            json=_mr_item,
            status=201,
        )

        # After creation: list MRs returns the open MR for all subsequent calls.
        # Covers: MR_MASTER_OPEN + BUMP_PENDING + BUMPED_LOCAL + DONE check in first run,
        # plus all calls in the second run (where it detects DONE immediately).
        for _ in range(30):
            responses.add(
                responses.GET,
                "https://gitlab.example/api/v4/projects/1/merge_requests",
                json=[_mr_item],
                status=200,
            )

        repo = tmp_repo_with_origin
        _setup_java_repo(repo)
        monkeypatch.chdir(repo)

        # Write config — use forward slashes so the path is valid inside a TOML
        # double-quoted string on Windows (backslashes would be treated as escapes).
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            _E2E_CONFIG.format(log_dir=str(tmp_path / "logs").replace("\\", "/")),
            encoding="utf-8",
        )

        # Decouple git remote URL from GitLab project lookup — same technique as Task 34.
        monkeypatch.setattr(GitLabClient, "project_path_from_url", lambda self, url: "org/app")

        # --- First run: full happy path CLEAN → DONE ---
        sp1 = ScriptedPrompter()
        sp1.queue([
            "1.0.0", "release/release-1.0.0",          # CLEAN
            "version freeze 1.0.0",                     # RELEASE_BRANCH_CREATED
            "yes",                                      # FROZEN_LOCAL push
            "yes", "Release 1.0.0",                     # FROZEN_PUSHED: confirm MR upfront, then title
            "yes", "1.0.1-SNAPSHOT", "version bump 1.0.1-SNAPSHOT",  # BUMP_PENDING: confirm + version + msg
            "yes", "yes",                               # BUMPED_LOCAL --ours, push
        ])
        sp1.queue_edit("body")
        monkeypatch.setattr("release_flow.prompts.QuestionaryPrompter", lambda: sp1)

        rc1 = main(["--config", str(cfg_path)])
        assert rc1 == 0

        # Capture how many POSTs were made after the first run (should be exactly 1: the MR).
        post_calls_after_first = sum(
            1 for c in responses.calls if c.request.method == "POST"
        )
        assert post_calls_after_first == 1, (
            f"Expected exactly 1 POST after first run, got {post_calls_after_first}"
        )

        pom_after_first = (repo / "pom.xml").read_text(encoding="utf-8")
        assert "1.0.1-SNAPSHOT" in pom_after_first

        # --- Second run: should detect DONE and exit 0 with no additional POST ---
        # No prompts should be needed — the orchestrator detects DONE on the first iteration
        # and returns immediately.
        sp2 = ScriptedPrompter()  # empty queue — no prompts should be consumed
        monkeypatch.setattr("release_flow.prompts.QuestionaryPrompter", lambda: sp2)

        rc2 = main(["--config", str(cfg_path)])
        assert rc2 == 0

        post_calls_after_second = sum(
            1 for c in responses.calls if c.request.method == "POST"
        )
        # No new MR should have been created on the second run.
        assert post_calls_after_second == post_calls_after_first, (
            f"Second run created additional POST requests: "
            f"before={post_calls_after_first}, after={post_calls_after_second}"
        )

        # Version files must be unchanged after the second run.
        pom_after_second = (repo / "pom.xml").read_text(encoding="utf-8")
        assert pom_after_second == pom_after_first, (
            "pom.xml was modified by the second run — idempotency violated"
        )
