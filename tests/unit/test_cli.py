"""Tests for CLI argparse and subcommand dispatch."""

import pytest

from release_flow.cli import build_parser


class TestArgParser:
    def test_default_command_is_main(self):
        parser = build_parser()
        ns = parser.parse_args([])
        assert ns.command in (None, "main")

    def test_status_subcommand(self):
        parser = build_parser()
        ns = parser.parse_args(["status"])
        assert ns.command == "status"

    def test_init_subcommand(self):
        parser = build_parser()
        ns = parser.parse_args(["init"])
        assert ns.command == "init"

    def test_doctor_subcommand(self):
        parser = build_parser()
        ns = parser.parse_args(["doctor"])
        assert ns.command == "doctor"

    def test_abort_subcommand(self):
        parser = build_parser()
        ns = parser.parse_args(["abort"])
        assert ns.command == "abort"

    def test_release_version_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--release-version", "1.0.0"])
        assert ns.release_version == "1.0.0"

    def test_dry_run_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["--dry-run"])
        assert ns.dry_run is True

    def test_no_confirm_flag(self):
        parser = build_parser()
        ns = parser.parse_args(["-y"])
        assert ns.no_confirm is True

    def test_unknown_force_delete_flag_rejected(self):
        # CRITICAL: there must be no flag to override protected branches
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--force-delete-develop"])
