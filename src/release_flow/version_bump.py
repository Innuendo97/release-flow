"""SemVer parsing and bumping. Pure module, no I/O."""

import re
from enum import StrEnum

from release_flow.exceptions import VersionParseError

# Suffix separators we recognise for SNAPSHOT versions. Maven uses '-SNAPSHOT'
# (the standard); some projects use '+SNAPSHOT' in non-Maven files such as
# pipeline.yaml. Both are treated as equivalent for comparison purposes; on
# write, the original file's separator is preserved.
SNAPSHOT_SEPARATORS = ("-", "+")

# Regex accepts both '-suffix' and '+suffix' (e.g. '1.2.3-SNAPSHOT' and
# '1.2.3+SNAPSHOT').
VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?(?:[-+](?P<suffix>.+))?$"
)


class BumpType(StrEnum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


def parse_version(s: str) -> tuple[int, int, int, str | None]:
    """Parse version string into (major, minor, patch, suffix_or_None).

    Suffix is everything after the first '-' or '+' (e.g. 'SNAPSHOT', 'RC1').
    Two-part versions like '1.2' are padded to '1.2.0'.
    """
    if not s:
        raise VersionParseError("empty version string")
    m = VERSION_RE.match(s.strip())
    if not m:
        raise VersionParseError(f"cannot parse version: {s!r}")
    major = int(m.group("major"))
    minor = int(m.group("minor"))
    patch = int(m.group("patch")) if m.group("patch") is not None else 0
    suffix = m.group("suffix")
    return (major, minor, patch, suffix)


def is_snapshot(version: str) -> bool:
    """True iff version ends in '-SNAPSHOT' or '+SNAPSHOT'."""
    return any(version.endswith(f"{sep}SNAPSHOT") for sep in SNAPSHOT_SEPARATORS)


def strip_snapshot(version: str) -> str:
    """Remove the SNAPSHOT suffix (either '-SNAPSHOT' or '+SNAPSHOT'). Idempotent."""
    for sep in SNAPSHOT_SEPARATORS:
        suffix = f"{sep}SNAPSHOT"
        if version.endswith(suffix):
            return version[: -len(suffix)]
    return version


def to_snapshot(version: str, separator: str = "-") -> str:
    """Append SNAPSHOT suffix using the given separator if not already present.

    `separator` defaults to '-' (Maven standard). Pass '+' for files that use
    the alternate convention (e.g. pipeline.yaml in some teams).
    """
    if is_snapshot(version):
        return version
    if separator not in SNAPSHOT_SEPARATORS:
        raise ValueError(
            f"separator must be one of {SNAPSHOT_SEPARATORS}, got {separator!r}"
        )
    return f"{version}{separator}SNAPSHOT"


def normalize_snapshot(version: str) -> str:
    """Return version with '+SNAPSHOT' rewritten as '-SNAPSHOT'.

    Use this when comparing versions that may come from files with different
    SNAPSHOT separator conventions (Maven uses '-', some YAML configs use '+').
    """
    return version.replace("+SNAPSHOT", "-SNAPSHOT")


def bump_version(version: str, bump: BumpType) -> str:
    """Bump major/minor/patch component, preserving any non-SNAPSHOT suffix.

    For MINOR bump, patch is reset to 0.
    For MAJOR bump, minor and patch are reset to 0.
    """
    major, minor, patch, suffix = parse_version(version)
    if bump == BumpType.PATCH:
        patch += 1
    elif bump == BumpType.MINOR:
        minor += 1
        patch = 0
    elif bump == BumpType.MAJOR:
        major += 1
        minor = 0
        patch = 0
    base = f"{major}.{minor}.{patch}"
    return f"{base}-{suffix}" if suffix else base
