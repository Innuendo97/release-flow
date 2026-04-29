import pytest

from release_flow.prompts import Prompter, ScriptedPrompter


class TestScriptedPrompter:
    """Test ScriptedPrompter implements Prompter protocol."""

    prompter: Prompter  # Type hint to use Prompter protocol

    def test_returns_queued_answers_in_order(self):
        p = ScriptedPrompter()
        p.queue(["1.0.0", "yes", "Release 1.0.0"])
        assert p.ask("Versione?", default="1.0.1") == "1.0.0"
        assert p.confirm("Procedo?") is True
        assert p.ask("Titolo?", default="x") == "Release 1.0.0"

    def test_confirm_false_when_answer_is_no(self):
        p = ScriptedPrompter()
        p.queue(["no"])
        assert p.confirm("Procedo?") is False

    def test_uses_default_when_answer_is_empty(self):
        p = ScriptedPrompter()
        p.queue([""])
        assert p.ask("Versione?", default="1.0.0") == "1.0.0"

    def test_raises_when_queue_exhausted(self):
        p = ScriptedPrompter()
        with pytest.raises(IndexError):
            p.ask("Q?", default="x")

    def test_edit_text_returns_canned(self):
        p = ScriptedPrompter()
        p.queue_edit("# MR Body\nlinea 2\n")
        result = p.edit_text(initial="# placeholder\n")
        assert "MR Body" in result
