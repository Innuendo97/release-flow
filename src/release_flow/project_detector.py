"""Detect project type from marker files. Pure module, no network/git I/O."""

from pathlib import Path
from typing import Any

from release_flow.exceptions import ProjectDetectionError

ProjectType = str  # alias for clarity; values come from config keys


def detect_project_type(
    repo_root: Path, project_types: dict[str, dict[str, Any]]
) -> ProjectType:
    """Return the first project type whose `detect` markers all match.

    A marker like 'pom.xml' must EXIST. A marker like '!pom.xml' must NOT exist.
    Iterates project_types in dict insertion order — config order wins.
    """
    for type_name, type_def in project_types.items():
        markers: list[str] = type_def.get("detect", [])
        if _all_markers_match(repo_root, markers):
            return type_name
    raise ProjectDetectionError(
        f"no project type matched in {repo_root}; "
        f"checked: {list(project_types.keys())}"
    )


def _all_markers_match(repo_root: Path, markers: list[str]) -> bool:
    for marker in markers:
        if marker.startswith("!"):
            forbidden = marker[1:]
            if (repo_root / forbidden).exists():
                return False
        else:
            if not (repo_root / marker).exists():
                return False
    return True
