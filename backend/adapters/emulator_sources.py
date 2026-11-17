"""Emulator sources — the one place the resolver's installations are detected and held.

Every adapter that puts a question to the vendored
`emu-atlas <https://github.com/danielcopper/emu-atlas>`_ resolver gets its
installation from here and never detects one itself. A question goes to the
source :func:`domain.emulator_sources.answering_source_for` names for the
game's system, or :func:`~domain.emulator_sources.answering_source` for a
question about no one system; the order, the switches and the Eden AppImage
named are the user's, read from the live settings.

**Detected per reading, never at construction.** A reading
(:class:`DetectedSourcesReading`) is taken per question a panel call puts, or
once per run that asks the same questions for many games, so a source installed
later appears on the next one. Building this adapter detects nothing, which is
what lets the pre-install check build it unchanged.

**One machine for the process.** ``atlas.detect`` builds a fresh
``RealMachine`` whenever it is handed none, and that object is where the
resolver remembers a libretro core's probe — a subprocess that loads the core,
which a fresh machine runs again on every save question. The memory is keyed
on the core file's path, modification time and size (``RealMachine.read_core``,
atlas 0.21.0), so keeping one machine keeps every answer live while the probe
of an unchanged core runs once.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from _vendor.atlas import (
    AVAILABILITY_STARTABLE,
    AVAILABILITY_UNESTABLISHED,
    CAVEAT_EMULATOR_CATALOGUE_SEALED,
    HEALTH_ISSUE_APPIMAGE_AMBIGUOUS,
    detect,
)
from _vendor.atlas.machine import RealMachine

from adapters.atlas_catalogue import catalogue_refused
from domain.emulator_sources import (
    CATALOGUE_READ,
    CATALOGUE_SEALED,
    CATALOGUE_UNAVAILABLE,
    EDEN_APPIMAGE_SETTING,
    ORDER_SETTING,
    SEVERAL_APPIMAGES,
    SWITCHED_OFF_SETTING,
    ArrangedSource,
    SourceFinding,
    SourceReport,
    SystemListing,
    answering_source,
    answering_source_for,
    arrange_sources,
    is_absolute_path,
    no_answering_source_reason,
    stored_kinds,
    switched_off_starting_source,
)
from domain.source_roots import (
    ROOT_INSTALLATION,
    ROOT_ROMS,
    SourceRoot,
    SourceRoots,
    explains_roots,
    reported_findings,
)
from domain.tender_folder import SourceRomFolders

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Mapping

    from domain.emulator_sources import SourcesReading


def source_roots(answer: Any) -> SourceRoots:
    """The resolver's roots answer as Tender's value: each root's path, provenance and settings file; its findings."""
    return SourceRoots(
        roots=tuple(
            SourceRoot(
                name=root.root,
                path=root.path,
                provenance=root.provenance,
                settings_file=root.setting.file if root.setting is not None else None,
            )
            for root in answer.roots
        ),
        findings=tuple(
            SourceFinding(code=caveat.code, data={str(key): str(value) for key, value in caveat.data.items()})
            for caveat in answer.caveats
        ),
    )


class DetectedSourcesReading:
    """One reading of the emulator sources (:class:`domain.emulator_sources.SourcesReading`).

    Holds the installations detected for it, the user's arrangement of them as
    it stood when the reading was taken, and a memory of the questions put
    through :meth:`remember`. The memory lives exactly as long as the reading,
    so a reading is kept no longer than the call or the run that took it.
    """

    def __init__(
        self,
        *,
        installations: tuple[Any, ...],
        sources: tuple[ArrangedSource, ...],
        switched_off: frozenset[str] = frozenset(),
        detection_failed: bool = False,
        log_debug: Callable[[str], None] = lambda _line: None,
    ) -> None:
        self._log_debug = log_debug
        self._detected = installations
        self._installations = {installation.kind: installation for installation in installations}
        self._sources = sources
        self._switched_off = switched_off
        self._detection_failed = detection_failed
        self._answering = answering_source(sources)
        self._answers: dict[Hashable, Any] = {}

    @property
    def installations(self) -> tuple[Any, ...]:
        """The resolver's handles detected for this reading, in its probe order."""
        return self._detected

    @property
    def sources(self) -> tuple[ArrangedSource, ...]:
        """Every detected source, in the user's order."""
        return self._sources

    @property
    def detection_failed(self) -> bool:
        """Whether detecting the sources raised, so that none detected establishes nothing about any of them.

        RetroDECK's folders (``adapters/retrodeck_folders.py``), the platform's
        system (``adapters/atlas_platforms.py``), the launch check
        (``services/emulator_sources.py``) and the ROM folders a place for
        Tender's folder is judged against (:meth:`EmulatorSourcesAdapter.rom_folders`)
        read it; every other reader takes such a reading as one that detected
        nothing.
        """
        return self._detection_failed

    def switched_off(self, kind: str) -> bool:
        """Whether the user switched the source of *kind* off — detected in this reading or not."""
        return kind in self._switched_off

    @property
    def answering(self) -> ArrangedSource | None:
        """The source a question about no one system goes to, or ``None`` where none answers."""
        return self._answering

    @property
    def answering_kind(self) -> str | None:
        """The kind of :attr:`answering`, or ``None``."""
        return self._answering.kind if self._answering is not None else None

    def answering_for(self, system: str) -> ArrangedSource | None:
        """The source a question about one of *system*'s games goes to, or ``None`` where none answers."""
        return self.remember(
            ("answering_for", system),
            lambda: answering_source_for(self._sources, lambda kind: self._listing(kind, system)),
        )

    def answering_kind_for(self, system: str | None) -> str | None:
        """The kind of :meth:`answering_for` *system*, or of :attr:`answering` without one; or ``None``."""
        source = self._answering if system is None else self.answering_for(system)
        return source.kind if source is not None else None

    def switched_off_starting_for(self, system: str | None) -> str | None:
        """The kind of the switched-off source that would start a *system* game, or ``None``.

        :func:`domain.emulator_sources.switched_off_starting_source`, asked for
        *system* where one is named.
        """
        if system is None:
            return switched_off_starting_source(self._sources)
        return switched_off_starting_source(self._sources, lambda kind: self._listing(kind, system))

    def no_answer_reason(self) -> str:
        """Why no source answers: ``no_source`` or ``switched_off``."""
        return no_answering_source_reason(self._sources)

    def answering_installation(self, system: str | None = None) -> Any | None:
        """The resolver's handle for :meth:`answering_for` *system*, or for :attr:`answering` without one.

        ``None`` where no source answers.
        """
        kind = self.answering_kind_for(system)
        return self._installations[kind] if kind is not None else None

    def _listing(self, kind: str, system: str) -> SystemListing:
        """How the source of *kind* lists *system*: read off its catalogue's entries, once per reading.

        A catalogue that raised, or that answered with one of the catalogue
        refusals, lists nothing.
        """
        installation = self._installations.get(kind)
        if installation is None:
            return SystemListing.NOT_LISTED

        def ask() -> SystemListing:
            try:
                answer = installation.emulators_for(system)
            except Exception as exc:
                # Deliberately broad, for the reason ``EmulatorSourcesAdapter.read`` gives.
                self._log_debug(f"[sources] {kind}: resolver failed on emulators_for({system!r}): {exc!r}")
                return SystemListing.NOT_LISTED
            if catalogue_refused(answer):
                return SystemListing.NOT_LISTED
            said = {entry.availability for entry in answer.entries}
            if AVAILABILITY_STARTABLE in said:
                return SystemListing.STARTS
            return SystemListing.UNESTABLISHED if AVAILABILITY_UNESTABLISHED in said else SystemListing.NOT_LISTED

        return self.remember(("system_listing", kind, system), ask)

    def installation(self, kind: str) -> Any | None:
        """The resolver's handle for the detected source of *kind*, or ``None``."""
        return self._installations.get(kind)

    def remember[T](self, question: Hashable, ask: Callable[[], T]) -> T:
        """The answer to *question* through this reading, asked on its first use only."""
        if question not in self._answers:
            self._answers[question] = ask()
        return self._answers[question]


class EmulatorSourcesAdapter:
    """Detects the emulator sources and arranges them by the user's settings.

    Implements the ``EmulatorSourcesReader`` Protocol structurally. *settings*
    is the live settings dict, read at every :meth:`read`, so a switch or a move
    written through the settings' owner takes effect on the next reading.
    """

    def __init__(
        self,
        *,
        user_home: str,
        settings: Mapping[str, Any],
        log_debug: Callable[[str], None],
        detect_installations: Callable[..., list[Any]] = detect,
        machine: Any = None,
    ) -> None:
        self._user_home = user_home
        self._settings = settings
        self._log_debug = log_debug
        self._detect = detect_installations
        self._machine = machine if machine is not None else RealMachine()

    def read(self) -> DetectedSourcesReading:
        """A fresh reading: detect the sources, and arrange them as the settings stand now."""
        failed = False
        named = self._named_eden_appimage()
        try:
            if named is None:
                installations = tuple(self._detect(self._user_home, self._machine))
            else:
                installations = tuple(self._detect(self._user_home, self._machine, eden_appimage=named))
        except Exception as exc:
            # Deliberately broad: detection is the resolver's own, and the
            # honest answer to "could not detect" is the same whatever raised.
            self._log_debug(f"[sources] detection failed, answering with none: {exc!r}")
            installations, failed = (), True
        reading = self._arranged(installations, detection_failed=failed)
        self._log_debug(
            f"[sources] detected={[source.kind for source in reading.sources]} "
            f"off={[source.kind for source in reading.sources if not source.enabled]} "
            f"answering={reading.answering_kind}"
        )
        return reading

    def _named_eden_appimage(self) -> str | None:
        """The Eden AppImage the user named, or ``None`` where none is, or the stored value is not an absolute path."""
        value = self._settings.get(EDEN_APPIMAGE_SETTING)
        if not isinstance(value, str) or value == "":
            return None
        if not is_absolute_path(value):
            self._log_debug(f"[sources] the stored Eden AppImage {value!r} is not an absolute path; searching instead")
            return None
        return value

    def describe(self, reading: SourcesReading | None = None) -> tuple[SourceReport, ...]:
        """Every detected source as the settings list shows it.

        Over the sources *reading* detected, arranged as the settings stand now,
        so a write's answer describes what the write found without detecting
        again; without one, from a fresh reading.
        """
        arranged = self._arranged(reading.installations) if reading is not None else self.read()
        return tuple(self._report(source, arranged.installation(source.kind)) for source in arranged.sources)

    def rom_folders(self) -> tuple[SourceRomFolders, ...] | None:
        """Every detected source's ROM folder and each system folder it names, symlink-resolved; ``None`` when unread.

        Every source counts, switched on or off, and a ROM folder counts
        whatever its provenance — read, the frontend's default, or only
        assumed. ``None`` where detecting the sources raised, or where a
        question to one of them did: a folder that was not read could be the
        one a place lies in.
        """
        reading = self.read()
        if reading.detection_failed:
            return None
        folders: list[SourceRomFolders] = []
        for installation in reading.installations:
            try:
                folders.append(_rom_folders_of(installation))
            except Exception as exc:
                # Deliberately broad, for the reason ``read`` gives.
                self._log_debug(f"[sources] {installation.kind}: resolver failed on its ROM folders: {exc!r}")
                return None
        return tuple(folders)

    def _arranged(self, installations: tuple[Any, ...], *, detection_failed: bool = False) -> DetectedSourcesReading:
        switched_off = frozenset(stored_kinds(self._settings.get(SWITCHED_OFF_SETTING)))
        sources = arrange_sources(
            detected=tuple(installation.kind for installation in installations),
            stored_order=stored_kinds(self._settings.get(ORDER_SETTING)),
            switched_off=switched_off,
        )
        return DetectedSourcesReading(
            installations=installations,
            sources=sources,
            switched_off=switched_off,
            detection_failed=detection_failed,
            log_debug=self._log_debug,
        )

    def _report(self, source: ArrangedSource, installation: Any) -> SourceReport:
        findings = self._findings(source.kind, installation)
        if getattr(installation, "roots", None) is None:
            # A source with no roots question (a bare RetroArch) states no
            # provenance: its root is shown as the resolver gives it, except
            # while a finding says its settings file was not read.
            explained = any(explains_roots(finding) for finding in findings)
            root = None if explained else self._ask(source.kind, "root", installation.root)
        else:
            answer = self._ask(source.kind, "roots", installation.roots)
            roots = None if answer is None else source_roots(answer)
            installation_root = None if roots is None else roots.root(ROOT_INSTALLATION)
            root = installation_root.path if installation_root is not None and installation_root.usable else None
            if roots is not None:
                findings = reported_findings(roots, findings)
        return SourceReport(
            kind=source.kind,
            enabled=source.enabled,
            starts_games=source.starts_games,
            root=root,
            findings=findings,
            catalogue=self._catalogue_state(source.kind, installation),
        )

    def _findings(self, kind: str, installation: Any) -> tuple[SourceFinding, ...]:
        health = self._ask(kind, "health", installation.health)
        if health is None:
            return ()
        return tuple(_finding(issue) for issue in health.issues)

    def _catalogue_state(self, kind: str, installation: Any) -> str:
        answer = self._ask(kind, "systems", installation.systems)
        if answer is None:
            return CATALOGUE_UNAVAILABLE
        if any(caveat.code == CAVEAT_EMULATOR_CATALOGUE_SEALED for caveat in answer.caveats):
            return CATALOGUE_SEALED
        return CATALOGUE_UNAVAILABLE if catalogue_refused(answer) else CATALOGUE_READ

    def _ask(self, kind: str, subject: str, question: Callable[[], Any]) -> Any:
        try:
            return question()
        except Exception as exc:
            self._log_debug(f"[sources] {kind}: resolver failed on {subject}: {exc!r}")
            return None


def _finding(issue: Any) -> SourceFinding:
    """One health issue as a finding, its data restated as plain strings.

    Several AppImages found is Tender's own :data:`~domain.emulator_sources.SEVERAL_APPIMAGES`,
    its candidates one path per line.
    """
    if issue.code == HEALTH_ISSUE_APPIMAGE_AMBIGUOUS:
        candidates = issue.data.get("candidates", ())
        return SourceFinding(code=SEVERAL_APPIMAGES, data={"candidates": "\n".join(str(path) for path in candidates)})
    return SourceFinding(code=issue.code, data={str(key): str(value) for key, value in issue.data.items()})


def _rom_folders_of(installation: Any) -> SourceRomFolders:
    """*installation*'s ROM folder and its systems' folders, resolved; raises what the resolver raises."""
    rom_root = None
    if getattr(installation, "roots", None) is not None:
        path = source_roots(installation.roots()).root(ROOT_ROMS).path
        rom_root = os.path.realpath(path) if path else None
    system_folders: list[tuple[str, str]] = []
    # One question for every system: the catalogue is read once, not once per system.
    for entry in installation.rom_locations().placements:
        folder = entry.placement.dir
        if folder:
            system_folders.append((entry.system, os.path.realpath(folder)))
    return SourceRomFolders(kind=installation.kind, rom_root=rom_root, system_folders=tuple(system_folders))
