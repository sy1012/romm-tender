"""In-memory ``EmulatorSourcesReader`` implementation for service tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from domain.emulator_sources import (
    ArrangedSource,
    SystemListing,
    answering_source,
    answering_source_for,
    no_answering_source_reason,
    switched_off_starting_source,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable

    from domain.emulator_sources import SourceReport
    from domain.tender_folder import SourceRomFolders

_T = TypeVar("_T")


class FakeSourcesReading:
    """A reading over fixed sources, with the same answer memory the real one keeps.

    ``listings`` maps ``(kind, system)`` to how that source lists the system;
    a pair it does not hold is not listed.
    """

    def __init__(
        self,
        sources: tuple[ArrangedSource, ...],
        installations: dict[str, Any],
        listings: dict[tuple[str, str], SystemListing] | None = None,
    ) -> None:
        self.sources = sources
        self._installations = installations
        self._listings = listings or {}
        self.installations = tuple(installations.values())
        self.answering = answering_source(sources)
        self.detection_failed = False
        self._answers: dict[Hashable, Any] = {}

    def _listing(self, system: str) -> Callable[[str], SystemListing]:
        return lambda kind: self._listings.get((kind, system), SystemListing.NOT_LISTED)

    def answering_for(self, system: str) -> ArrangedSource | None:
        return answering_source_for(self.sources, self._listing(system))

    def switched_off_starting_for(self, system: str | None) -> str | None:
        if system is None:
            return switched_off_starting_source(self.sources)
        return switched_off_starting_source(self.sources, self._listing(system))

    def no_answer_reason(self) -> str:
        return no_answering_source_reason(self.sources)

    def answering_installation(self, system: str | None = None) -> Any:
        answering = self.answering if system is None else self.answering_for(system)
        return self._installations.get(answering.kind) if answering is not None else None

    def installation(self, kind: str) -> Any:
        return self._installations.get(kind)

    def remember(self, question: Hashable, ask: Callable[[], _T]) -> _T:
        if question not in self._answers:
            self._answers[question] = ask()
        return self._answers[question]


class FakeEmulatorSources:
    """Hands out readings over the sources a test named and counts them.

    ``sources`` defaults to one RetroDECK, switched on. ``installations`` maps a
    kind to the object a reading answers as that source's installation.
    ``reports`` is what :meth:`describe` answers, ``rom_folders`` what
    :meth:`rom_folders` does. ``reads`` counts every reading
    taken, so a test can tell one reading per run from one per question.
    """

    def __init__(
        self,
        *,
        sources: tuple[ArrangedSource, ...] = (ArrangedSource(kind="retrodeck", enabled=True, starts_games=True),),
        installations: dict[str, Any] | None = None,
        reports: tuple[SourceReport, ...] = (),
        rom_folders: tuple[SourceRomFolders, ...] | None = (),
        listings: dict[tuple[str, str], SystemListing] | None = None,
    ) -> None:
        self.sources = sources
        self.listings = listings
        self.installations: dict[str, Any] = installations if installations is not None else {}
        self.reports = reports
        self.answered_rom_folders = rom_folders
        self.reads = 0
        self.taken: list[FakeSourcesReading] = []

    def read(self) -> FakeSourcesReading:
        self.reads += 1
        reading = FakeSourcesReading(self.sources, self.installations, self.listings)
        self.taken.append(reading)
        return reading

    def describe(self, reading: Any = None) -> tuple[SourceReport, ...]:
        return self.reports

    def rom_folders(self) -> tuple[SourceRomFolders, ...] | None:
        return self.answered_rom_folders
