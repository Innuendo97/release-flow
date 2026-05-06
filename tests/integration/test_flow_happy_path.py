import pytest
import responses

from release_flow.config import (
    BehaviorConfig,
    Config,
    DefaultsConfig,
    GitLabConfig,
    LoggingConfig,
    ProjectTypeConfig,
)
from release_flow.flow import run as flow_run
from release_flow.gitlab_client import GitLabClient
from release_flow.prompts import ScriptedPrompter


def _make_config() -> Config:
    return Config(
        gitlab=GitLabConfig(base_url="https://gitlab.example", token="glpat-x"),
        defaults=DefaultsConfig(
            develop_branch="develop", master_branch="master",
            release_branch_prefix="release/release-", default_bump="patch",
            freeze_commit_msg="version freeze {version}",
            bump_commit_msg="version bump {next_version}",
            merge_back_commit_msg="Merge release {version} into develop",
            mr_master_title="Release {version}",
            mr_master_body_template="## Release {version}\n",
        ),
        behavior=BehaviorConfig(
            confirm_before_push=True, confirm_before_mr=True,
            open_mr_in_browser_after_create=False, mr_develop_strategy="direct_push",
        ),
        logging=LoggingConfig(log_dir="/tmp/logs", log_retention_days=30, verbose_default=False),
        project_types={
            "java": ProjectTypeConfig(
                detect=["pom.xml"], primary_file="pom.xml",
                secondary_files=["chart/Chart.yaml", "pipeline.yaml"],
            ),
        },
        repo_overrides={},
    )


@pytest.mark.integration
class TestFlowHappyPath:
    @responses.activate
    def test_clean_to_done(self, tmp_repo_with_origin):
        # Set up GitLab mocks. The orchestrator calls list_open_mrs (which also
        # calls projects.get) on EVERY iteration, so we need many repeated mocks.
        # We register enough to cover all iterations; responses are consumed in order.

        _mr_item = {
            "iid": 142, "title": "Release 1.0.0",
            "source_branch": "release/release-1.0.0", "target_branch": "master",
            "state": "opened",
            "web_url": "https://gitlab.example/org/app/-/merge_requests/142",
            "author": {"username": "me"},
        }

        # project lookup — needed once per list_open_mrs call; add ~20 to be safe
        for _ in range(20):
            responses.get(
                "https://gitlab.example/api/v4/projects/org%2Fapp",
                json={"id": 1, "path": "app"},
                status=200,
            )

        # Before MR creation: list MRs returns [].
        # Calls: iter2 top (RELEASE_BRANCH_CREATED) + iter3 top (FROZEN_LOCAL)
        # + iter4 top (FROZEN_PUSHED) + iter4 idempotency inside execute_phase_frozen_pushed
        # = 4 empty calls before the POST.
        for _ in range(4):
            responses.add(
                responses.GET,
                "https://gitlab.example/api/v4/projects/1/merge_requests",
                json=[], status=200,
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

        repo = tmp_repo_with_origin
        # Set up java project on develop
        from .test_flow_phases import _setup_java_repo
        _setup_java_repo(repo)

        cfg = _make_config()
        client = GitLabClient(
            base_url=cfg.gitlab.base_url, token=cfg.gitlab.token
        )
        prompter = ScriptedPrompter()
        prompter.queue([
            # Phase CLEAN
            "1.0.0",                          # release version
            "release/release-1.0.0",          # branch name
            # Phase RELEASE_BRANCH_CREATED
            "version freeze 1.0.0",           # commit message
            # Phase FROZEN_LOCAL
            "yes",                            # confirm push
            # Phase FROZEN_PUSHED (MR creation)
            "yes",                            # confirm MR creation upfront
            "Release 1.0.0",                  # MR title
            # Phase BUMP_PENDING
            "yes",                            # confirm bump upfront
            "1.0.1-SNAPSHOT",                 # next version
            "version bump 1.0.1-SNAPSHOT",    # commit message
            # Phase BUMPED_LOCAL
            "yes",                            # confirm --ours
            "yes",                            # confirm push develop
        ])
        prompter.queue_edit("## Release 1.0.0\nbody\n")

        result = flow_run(
            repo_root=repo,
            config=cfg,
            gitlab=client,
            prompter=prompter,
            allow_dirty=False,
            project_path="org/app",  # bypass remote URL parsing (local bare repo)
        )
        assert result.final_phase.name == "DONE"
        # version files now have next-snapshot
        assert "1.0.1-SNAPSHOT" in (repo / "pom.xml").read_text(encoding="utf-8")
