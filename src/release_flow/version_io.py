"""Read/write versions in version-bearing files. Pure I/O on local files."""

import re
from dataclasses import dataclass
from pathlib import Path

from release_flow.exceptions import VersionParseError

# Built-in patterns. Each entry: file glob → (primary_pattern, secondary_patterns).
# `primary_pattern` matches the AUTHORITATIVE version; `secondary_patterns` are
# all loci where the version must also appear (and stay synchronized).

POM_PRIMARY_PATTERN = re.compile(
    r"<artifactId>(?P<artifact>[^<]+)</artifactId>\s*<version>(?P<v>[^<]+)</version>",
    re.MULTILINE,
)


@dataclass(frozen=True)
class VersionMatch:
    file: Path
    line: int
    matched_version: str
    full_match_text: str


def read_pom_version(pom_path: Path) -> str:
    """Return the project's <version> from a pom.xml.

    Distinguishes project version from parent.version by anchoring on the
    project's own <artifactId>. Picks the FIRST <artifactId>...<version>
    pair that isn't inside <parent>.
    """
    content = pom_path.read_text(encoding="utf-8")
    # Strip <parent>...</parent> first to avoid matching parent.version
    no_parent = re.sub(r"<parent>.*?</parent>", "", content, flags=re.DOTALL)
    m = POM_PRIMARY_PATTERN.search(no_parent)
    if not m:
        raise VersionParseError(f"no <artifactId>+<version> found in {pom_path}")
    return m.group("v").strip()


def write_version_in_file(
    file_path: Path,
    old_version: str,
    new_version: str,
    anchor_pattern: str,
) -> int:
    """Replace `old_version` with `new_version` ONLY where the anchor matches.

    Returns the number of replacements made (0 if old_version not found —
    caller should treat 0 as idempotent no-op when new_version already in place).
    """
    content = file_path.read_text(encoding="utf-8")
    pattern = re.compile(anchor_pattern, re.MULTILINE | re.DOTALL)
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        full = match.group(0)
        v = match.group("v")
        if v.strip() != old_version:
            return full  # leave alone — not the version we're updating
        count += 1
        return full.replace(old_version, new_version)

    new_content = pattern.sub(_replace, content)
    if count > 0:
        file_path.write_text(new_content, encoding="utf-8")
    return count


# Chart.yaml top-level keys 'version' and 'appVersion'.
# Anchored to start-of-line (^) to avoid matching nested keys.
CHART_PRIMARY_PATTERN = r"^version:\s*(?P<v>\S.*?)\s*$"
CHART_SECONDARY_PATTERNS = [
    r"^appVersion:\s*(?P<v>\S.*?)\s*$",
    r"^version:\s*(?P<v>\S.*?)\s*$",
]


def find_version_occurrences(
    file_path: Path, patterns: list[str]
) -> list[VersionMatch]:
    """Find every occurrence of every pattern in file. Returns list of matches.

    Useful for diagnostics and for verifying secondary-file consistency.
    """
    content = file_path.read_text(encoding="utf-8")
    matches: list[VersionMatch] = []
    for pat in patterns:
        compiled = re.compile(pat, re.MULTILINE)
        for m in compiled.finditer(content):
            line = content.count("\n", 0, m.start()) + 1
            matches.append(
                VersionMatch(
                    file=file_path,
                    line=line,
                    matched_version=m.group("v").strip(),
                    full_match_text=m.group(0),
                )
            )
    return matches


def read_chart_version(chart_path: Path) -> str:
    """Read the `version:` top-level key from a Chart.yaml."""
    matches = find_version_occurrences(chart_path, [CHART_PRIMARY_PATTERN])
    if not matches:
        raise VersionParseError(f"no top-level 'version:' in {chart_path}")
    return matches[0].matched_version


# pipeline.yaml: matches `VERSION_TO_INSTALL: "..."`
PIPELINE_SECONDARY_PATTERN = r'VERSION_TO_INSTALL:\s*"(?P<v>[^"]+)"'

# package.json: top-level "version": "..." — anchored to start-of-line + 2 spaces
# (rules out nested dependency versions which are deeper in the JSON tree).
PACKAGE_JSON_PATTERN = r'^\s{0,4}"version":\s*"(?P<v>[^"]+)"'

# Go: const Version = "..."
GO_CONST_PATTERN = r'(?:const\s+)?Version\s*=\s*"(?P<v>[^"]+)"'
