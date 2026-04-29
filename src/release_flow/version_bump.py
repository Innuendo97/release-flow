"""SemVer parsing and bumping. Pure module, no I/O."""

import re
from enum import StrEnum

from release_flow.exceptions import VersionParseError

VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?(?:-(?P<suffix>.+))?$"
)


class BumpType(StrEnum):
    PATCH = "patch"
    MINOR = "minor"
    MAJOR = "major"


def parse_version(s: str) -> tuple[int, int, int, str | None]:
    """Parse version string into (major, minor, patch, suffix_or_None).

    Suffix is everything after the first '-' (e.g. 'SNAPSHOT', 'RC1').
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
    """True iff version ends in '-SNAPSHOT' (Maven convention)."""
    return version.endswith("-SNAPSHOT")


def strip_snapshot(version: str) -> str:
    """Remove '-SNAPSHOT' suffix if present. Idempotent."""
    return version[: -len("-SNAPSHOT")] if is_snapshot(version) else version


def to_snapshot(version: str) -> str:
    """Append '-SNAPSHOT' if not already present. Idempotent."""
    return version if is_snapshot(version) else f"{version}-SNAPSHOT"


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
