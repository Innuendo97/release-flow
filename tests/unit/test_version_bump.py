import pytest
from hypothesis import given
from hypothesis import strategies as st

from release_flow.exceptions import VersionParseError
from release_flow.version_bump import (
    BumpType,
    bump_version,
    is_snapshot,
    parse_version,
    strip_snapshot,
    to_snapshot,
)


class TestParseVersion:
    def test_simple_three_part(self):
        assert parse_version("1.2.3") == (1, 2, 3, None)

    def test_with_snapshot(self):
        assert parse_version("1.2.3-SNAPSHOT") == (1, 2, 3, "SNAPSHOT")

    def test_with_rc_suffix(self):
        assert parse_version("2.0.0-RC1") == (2, 0, 0, "RC1")

    def test_two_part_padded_to_three(self):
        assert parse_version("1.2") == (1, 2, 0, None)

    def test_invalid_raises(self):
        with pytest.raises(VersionParseError):
            parse_version("abc")

    def test_empty_raises(self):
        with pytest.raises(VersionParseError):
            parse_version("")


class TestIsSnapshot:
    def test_with_snapshot(self):
        assert is_snapshot("1.2.3-SNAPSHOT") is True

    def test_without_snapshot(self):
        assert is_snapshot("1.2.3") is False

    def test_rc_is_not_snapshot(self):
        assert is_snapshot("1.2.3-RC1") is False


class TestStripSnapshot:
    def test_strips(self):
        assert strip_snapshot("1.2.3-SNAPSHOT") == "1.2.3"

    def test_idempotent_when_no_snapshot(self):
        assert strip_snapshot("1.2.3") == "1.2.3"


class TestToSnapshot:
    def test_adds(self):
        assert to_snapshot("1.2.3") == "1.2.3-SNAPSHOT"

    def test_idempotent_when_already_snapshot(self):
        assert to_snapshot("1.2.3-SNAPSHOT") == "1.2.3-SNAPSHOT"


class TestBumpVersion:
    def test_bump_patch(self):
        assert bump_version("1.2.3", BumpType.PATCH) == "1.2.4"

    def test_bump_minor_resets_patch(self):
        assert bump_version("1.2.3", BumpType.MINOR) == "1.3.0"

    def test_bump_major_resets_minor_and_patch(self):
        assert bump_version("1.2.3", BumpType.MAJOR) == "2.0.0"

    def test_bump_preserves_no_suffix(self):
        # bump_version operates on numeric part only
        assert bump_version("1.2.3-SNAPSHOT", BumpType.PATCH) == "1.2.4-SNAPSHOT"

    def test_bump_preserves_rc_suffix(self):
        assert bump_version("1.2.3-RC1", BumpType.PATCH) == "1.2.4-RC1"


class TestPropertyBased:
    @given(
        major=st.integers(min_value=0, max_value=999),
        minor=st.integers(min_value=0, max_value=999),
        patch=st.integers(min_value=0, max_value=999),
    )
    def test_parse_roundtrip(self, major, minor, patch):
        v = f"{major}.{minor}.{patch}"
        assert parse_version(v) == (major, minor, patch, None)

    @given(
        major=st.integers(min_value=0, max_value=999),
        minor=st.integers(min_value=0, max_value=999),
        patch=st.integers(min_value=0, max_value=999),
    )
    def test_strip_then_to_snapshot_idempotent(self, major, minor, patch):
        v = f"{major}.{minor}.{patch}"
        assert to_snapshot(strip_snapshot(to_snapshot(v))) == f"{v}-SNAPSHOT"
