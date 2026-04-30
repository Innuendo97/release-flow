"""Tests for init subcommand (config wizard)."""

from argparse import Namespace

import responses

from release_flow.cli import _cmd_init


class TestInitCommand:
    @responses.activate
    def test_creates_config_file(self, tmp_path, monkeypatch):
        """Test that init creates a config file and validates the token."""
        # Mock token validation: GET /user → 200
        responses.get(
            "https://gitlab.example/api/v4/user",
            json={"username": "me", "name": "Me"},
            status=200,
        )
        cfg_path = tmp_path / "config.toml"
        # ScriptedPrompter: pre-fill answers
        from release_flow.prompts import ScriptedPrompter

        sp = ScriptedPrompter()
        sp.queue([
            "https://gitlab.example",  # base_url
            "glpat-xxx",  # token
            "patch",  # default bump
        ])
        monkeypatch.setattr("release_flow.cli._init_prompter", lambda: sp)
        result = _cmd_init(Namespace(config=cfg_path))
        assert result == 0
        assert cfg_path.exists()
        content = cfg_path.read_text(encoding="utf-8")
        assert "https://gitlab.example" in content
        assert "glpat-xxx" in content
