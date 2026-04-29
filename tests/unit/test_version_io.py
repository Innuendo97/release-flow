import pytest

from release_flow.exceptions import VersionParseError
from release_flow.version_io import read_pom_version, write_version_in_file

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
