import pytest

from release_flow.exceptions import ProjectDetectionError
from release_flow.project_detector import ProjectType, detect_project_type


def test_project_type_alias() -> None:
    """Verify ProjectType is a string alias."""
    result: ProjectType = "java"
    assert isinstance(result, str)


class TestDetectProjectType:
    def test_java_via_pom(self, tmp_path):
        (tmp_path / "pom.xml").touch()
        types = {
            "java": {"detect": ["pom.xml"]},
            "go": {"detect": ["go.mod"]},
        }
        assert detect_project_type(tmp_path, types) == "java"

    def test_go_via_gomod(self, tmp_path):
        (tmp_path / "go.mod").touch()
        types = {
            "java": {"detect": ["pom.xml"]},
            "go": {"detect": ["go.mod"]},
        }
        assert detect_project_type(tmp_path, types) == "go"

    def test_helm_only_with_negative_marker(self, tmp_path):
        # Chart.yaml present, pom.xml ABSENT — match "helm-only"
        (tmp_path / "Chart.yaml").touch()
        types = {
            "java": {"detect": ["pom.xml"]},
            "helm-only": {"detect": ["Chart.yaml", "!pom.xml", "!go.mod"]},
        }
        assert detect_project_type(tmp_path, types) == "helm-only"

    def test_negative_marker_blocks_match(self, tmp_path):
        # Both Chart.yaml AND pom.xml — helm-only should NOT match because of !pom.xml
        (tmp_path / "Chart.yaml").touch()
        (tmp_path / "pom.xml").touch()
        types = {
            "java": {"detect": ["pom.xml"]},
            "helm-only": {"detect": ["Chart.yaml", "!pom.xml"]},
        }
        assert detect_project_type(tmp_path, types) == "java"

    def test_no_match_raises(self, tmp_path):
        (tmp_path / "random.txt").touch()
        types = {"java": {"detect": ["pom.xml"]}}
        with pytest.raises(ProjectDetectionError) as exc:
            detect_project_type(tmp_path, types)
        assert "no project type matched" in str(exc.value).lower()

    def test_first_match_wins(self, tmp_path):
        # When two types match, the first-defined wins (deterministic order)
        (tmp_path / "pom.xml").touch()
        (tmp_path / "Chart.yaml").touch()
        types = {
            "java": {"detect": ["pom.xml"]},
            "helm-with-pom": {"detect": ["Chart.yaml"]},  # also matches
        }
        # dict preserves insertion order in 3.7+
        assert detect_project_type(tmp_path, types) == "java"
