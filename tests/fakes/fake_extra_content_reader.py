"""In-memory ``ExtraContentReader`` for service tests."""

from __future__ import annotations

from typing import Any

from domain.extra_content import NOT_OFFERED, ExtraContentFolders


class FakeExtraContentReader:
    """Answers ``answer`` for every question, and records each question in ``asked``.

    ``answer`` is the not-offered reading until a test sets one.
    """

    def __init__(self, answer: ExtraContentFolders = NOT_OFFERED) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str | None, str | None]] = []

    def extra_content_folders(
        self, system: str, *, label: str | None, content_path: str | None, reading: Any = None
    ) -> ExtraContentFolders:
        self.asked.append((system, label, content_path))
        return self.answer
