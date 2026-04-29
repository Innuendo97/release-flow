"""Prompter port: wizard interaction abstraction.

Two implementations:
  - QuestionaryPrompter: production, uses `questionary` for rich CLI prompts
  - ScriptedPrompter: test fake, returns canned answers from a queue
"""

from collections import deque
from typing import Protocol

import click
import questionary


class Prompter(Protocol):
    def ask(self, question: str, *, default: str = "") -> str: ...
    def confirm(self, question: str, *, default: bool = True) -> bool: ...
    def edit_text(self, *, initial: str = "") -> str: ...


class QuestionaryPrompter:
    def ask(self, question: str, *, default: str = "") -> str:
        answer = questionary.text(question, default=default).ask()
        if answer is None:  # user hit Ctrl+C
            raise KeyboardInterrupt()
        return answer if answer != "" else default

    def confirm(self, question: str, *, default: bool = True) -> bool:
        answer = questionary.confirm(question, default=default).ask()
        if answer is None:
            raise KeyboardInterrupt()
        return bool(answer)

    def edit_text(self, *, initial: str = "") -> str:
        edited = click.edit(initial)
        return edited if edited is not None else initial


class ScriptedPrompter:
    """Test fake. Pre-load answers via .queue() and .queue_edit()."""

    def __init__(self) -> None:
        self._answers: deque[str] = deque()
        self._edits: deque[str] = deque()

    def queue(self, answers: list[str]) -> None:
        self._answers.extend(answers)

    def queue_edit(self, text: str) -> None:
        self._edits.append(text)

    def ask(self, question: str, *, default: str = "") -> str:
        if not self._answers:
            raise IndexError(f"ScriptedPrompter exhausted on ask({question!r})")
        a = self._answers.popleft()
        return a if a != "" else default

    def confirm(self, question: str, *, default: bool = True) -> bool:
        if not self._answers:
            raise IndexError(f"ScriptedPrompter exhausted on confirm({question!r})")
        a = self._answers.popleft().lower().strip()
        if a in ("yes", "y", "true", "1"):
            return True
        if a in ("no", "n", "false", "0"):
            return False
        return default

    def edit_text(self, *, initial: str = "") -> str:
        if not self._edits:
            return initial
        return self._edits.popleft()
