import pytest

from release_flow.exceptions import VersionMismatchError, VersionParseError
from release_flow.version_io import (
    CHART_SECONDARY_PATTERNS,
    PIPELINE_SECONDARY_PATTERN,
    POM_PRIMARY_PATTERN,
    FileSpec,
    read_all_versions,
    read_pom_version,
    replace_version_in_files,
    verify_versions_consistent,
    write_version_in_file,
)

POM_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<project>
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.4.10</version>
    </parent>
    <groupId>it.poste.rds</groupId>
    <artifactId>service-rds-app</artifactId>
    <version>1.1.27-SNAPSHOT</version>
    <name>service-rds-app</name>
</project>
"""


class TestReadPomVersion:
    def test_reads_project_version_not_parent(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(POM_CONTENT, encoding="utf-8")
        assert read_pom_version(pom) == "1.1.27-SNAPSHOT"

    def test_raises_on_missing_version(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text("<project><artifactId>x</artifactId></project>", encoding="utf-8")
        with pytest.raises(VersionParseError):
            read_pom_version(pom)


class TestWriteVersionInFile:
    def test_replaces_exact_string_once(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(POM_CONTENT, encoding="utf-8")
        n = write_version_in_file(
            pom,
            old_version="1.1.27-SNAPSHOT",
            new_version="1.1.27",
            anchor_pattern=r"<artifactId>service-rds-app</artifactId>\s*<version>(?P<v>[^<]+)</version>",
        )
        assert n == 1
        content = pom.read_text(encoding="utf-8")
        assert "<version>1.1.27</version>" in content
        assert "<version>3.4.10</version>" in content  # parent unchanged

    def test_idempotent_when_already_target(self, tmp_path):
        pom = tmp_path / "pom.xml"
        pom.write_text(POM_CONTENT.replace("1.1.27-SNAPSHOT", "1.1.27"), encoding="utf-8")
        n = write_version_in_file(
            pom,
            old_version="1.1.27-SNAPSHOT",
            new_version="1.1.27",
            anchor_pattern=r"<artifactId>service-rds-app</artifactId>\s*<version>(?P<v>[^<]+)</version>",
        )
        assert n == 0  # nothing to do


CHART_CONTENT = """apiVersion: v2
appVersion: 1.1.27-SNAPSHOT
description: A Helm chart
name: service-rds-app
type: application
version: 1.1.27-SNAPSHOT
"""


class TestChartYaml:
    def test_finds_both_occurrences(self, tmp_path):
        from release_flow.version_io import (
            CHART_SECONDARY_PATTERNS,
            find_version_occurrences,
        )

        chart = tmp_path / "Chart.yaml"
        chart.write_text(CHART_CONTENT, encoding="utf-8")
        matches = find_version_occurrences(chart, CHART_SECONDARY_PATTERNS)
        assert len(matches) == 2
        assert all(m.matched_version == "1.1.27-SNAPSHOT" for m in matches)
        # both lines captured
        lines = sorted(m.line for m in matches)
        assert lines == [2, 6]

    def test_replaces_both_occurrences(self, tmp_path):
        from release_flow.version_io import CHART_SECONDARY_PATTERNS

        chart = tmp_path / "Chart.yaml"
        chart.write_text(CHART_CONTENT, encoding="utf-8")
        for pat in CHART_SECONDARY_PATTERNS:
            write_version_in_file(
                chart,
                old_version="1.1.27-SNAPSHOT",
                new_version="1.1.27",
                anchor_pattern=pat,
            )
        new = chart.read_text(encoding="utf-8")
        assert new.count("1.1.27") == 2
        assert "SNAPSHOT" not in new


PIPELINE_CONTENT = '''SVILUPPO:
  DEPLOY:
    service-rds-app:
      VERSION_TO_INSTALL: "1.1.27-SNAPSHOT"
      OCP_CLUSTER_URL: "https://example"
'''

PACKAGE_JSON_CONTENT = '''{
  "name": "my-app",
  "version": "1.1.27-SNAPSHOT",
  "dependencies": {
    "react": "1.1.27"
  }
}
'''

GO_CONST_CONTENT = '''package version

const Version = "1.1.27-SNAPSHOT"
'''


class TestPipelineYaml:
    def test_finds_version_to_install(self, tmp_path):
        from release_flow.version_io import (
            PIPELINE_SECONDARY_PATTERN,
            find_version_occurrences,
        )

        p = tmp_path / "pipeline.yaml"
        p.write_text(PIPELINE_CONTENT, encoding="utf-8")
        matches = find_version_occurrences(p, [PIPELINE_SECONDARY_PATTERN])
        assert len(matches) == 1
        assert matches[0].matched_version == "1.1.27-SNAPSHOT"


class TestPackageJson:
    def test_finds_top_level_version_only(self, tmp_path):
        from release_flow.version_io import (
            PACKAGE_JSON_PATTERN,
            find_version_occurrences,
        )

        p = tmp_path / "package.json"
        p.write_text(PACKAGE_JSON_CONTENT, encoding="utf-8")
        matches = find_version_occurrences(p, [PACKAGE_JSON_PATTERN])
        # MUST match top-level "version" only, NOT the dependency value
        assert len(matches) == 1
        assert matches[0].matched_version == "1.1.27-SNAPSHOT"


class TestGoConst:
    def test_finds_version_const(self, tmp_path):
        from release_flow.version_io import (
            GO_CONST_PATTERN,
            find_version_occurrences,
        )

        p = tmp_path / "version.go"
        p.write_text(GO_CONST_CONTENT, encoding="utf-8")
        matches = find_version_occurrences(p, [GO_CONST_PATTERN])
        assert len(matches) == 1
        assert matches[0].matched_version == "1.1.27-SNAPSHOT"


def _make_repo(tmp_path, pom_v, chart_v_appv, chart_v, pipeline_v):
    (tmp_path / "pom.xml").write_text(
        POM_CONTENT.replace("1.1.27-SNAPSHOT", pom_v), encoding="utf-8"
    )
    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    (chart_dir / "Chart.yaml").write_text(
        CHART_CONTENT
        .replace("appVersion: 1.1.27-SNAPSHOT", f"appVersion: {chart_v_appv}")
        .replace("version: 1.1.27-SNAPSHOT", f"version: {chart_v}"),
        encoding="utf-8",
    )
    (tmp_path / "pipeline.yaml").write_text(
        PIPELINE_CONTENT.replace("1.1.27-SNAPSHOT", pipeline_v), encoding="utf-8"
    )


class TestReadAllVersions:
    def test_reads_all(self, tmp_path):
        _make_repo(tmp_path, "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT")
        primary = FileSpec(path=tmp_path / "pom.xml", patterns=[POM_PRIMARY_PATTERN.pattern])
        secondaries = [
            FileSpec(path=tmp_path / "chart/Chart.yaml", patterns=CHART_SECONDARY_PATTERNS),
            FileSpec(path=tmp_path / "pipeline.yaml", patterns=[PIPELINE_SECONDARY_PATTERN]),
        ]
        primary_v, secondary_matches = read_all_versions(primary, secondaries)
        assert primary_v == "1.1.27-SNAPSHOT"
        assert len(secondary_matches) == 3  # 2 chart + 1 pipeline
        assert all(m.matched_version == "1.1.27-SNAPSHOT" for m in secondary_matches)


class TestVerifyConsistency:
    def test_consistent(self, tmp_path):
        _make_repo(tmp_path, "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT")
        primary = FileSpec(path=tmp_path / "pom.xml", patterns=[POM_PRIMARY_PATTERN.pattern])
        secondaries = [
            FileSpec(path=tmp_path / "chart/Chart.yaml", patterns=CHART_SECONDARY_PATTERNS),
            FileSpec(path=tmp_path / "pipeline.yaml", patterns=[PIPELINE_SECONDARY_PATTERN]),
        ]
        # should not raise
        verify_versions_consistent(primary, secondaries)

    def test_inconsistent_raises(self, tmp_path):
        _make_repo(tmp_path, "1.1.27-SNAPSHOT", "1.1.26", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT")
        primary = FileSpec(path=tmp_path / "pom.xml", patterns=[POM_PRIMARY_PATTERN.pattern])
        secondaries = [
            FileSpec(path=tmp_path / "chart/Chart.yaml", patterns=CHART_SECONDARY_PATTERNS),
        ]
        with pytest.raises(VersionMismatchError) as exc:
            verify_versions_consistent(primary, secondaries)
        assert "1.1.26" in str(exc.value)


class TestReplaceVersionInFiles:
    def test_replaces_everywhere(self, tmp_path):
        _make_repo(tmp_path, "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT", "1.1.27-SNAPSHOT")
        primary = FileSpec(path=tmp_path / "pom.xml", patterns=[POM_PRIMARY_PATTERN.pattern])
        secondaries = [
            FileSpec(path=tmp_path / "chart/Chart.yaml", patterns=CHART_SECONDARY_PATTERNS),
            FileSpec(path=tmp_path / "pipeline.yaml", patterns=[PIPELINE_SECONDARY_PATTERN]),
        ]
        n = replace_version_in_files(primary, secondaries, "1.1.27-SNAPSHOT", "1.1.27")
        assert n == 4  # 1 pom + 2 chart + 1 pipeline
        assert "1.1.27-SNAPSHOT" not in (tmp_path / "pom.xml").read_text(encoding="utf-8")
        assert "1.1.27-SNAPSHOT" not in (tmp_path / "chart/Chart.yaml").read_text(encoding="utf-8")
        assert "1.1.27-SNAPSHOT" not in (tmp_path / "pipeline.yaml").read_text(encoding="utf-8")
