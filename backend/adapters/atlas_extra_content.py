"""Atlas extra-content adapter — the one place the resolver's answer about updates and add-ons in folders is read.

The resolver answers, for the emulator entry a game starts with, whether that
emulator loads a game's updates and add-on content from packages lying in
folders, which folders it scans, which file extensions it reads there, and
whether the game's own folder is one of them (``extra_content_folders``). This
module reads that answer into Tender's view
(:class:`domain.extra_content.ExtraContentFolders`); nothing else in Tender
reads it.

Only a stated ``true`` offers extra content. ``null`` is the resolver saying it
has not established it for this entry (``extra-content-folders-unstated``),
which offers nothing and is never read as a "no". Where the game's folder is
scanned and every folder the answer lists is scanned only beside the launch
(``extra-content-scanned-beside-launch``, ``registered_before_launch`` null on
each), the view says so; where the answer lists a folder registered before the
launch as well, which of them holds the game's folder is not stated, and the
view says nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from _vendor.atlas import (
    CAVEAT_CONTENT_OUTSIDE_EXTRA_CONTENT_FOLDERS,
    CAVEAT_EXTRA_CONTENT_FOLDERS_UNSTATED,
    CAVEAT_EXTRA_CONTENT_SCANNED_BESIDE_LAUNCH,
)

from domain.extra_content import NOT_OFFERED, ExtraContentFolders

if TYPE_CHECKING:
    from collections.abc import Callable

    from adapters.emulator_sources import EmulatorSourcesAdapter
    from domain.emulator_sources import SourcesReading

# Notes the answer's own fields already say: an entry whose reading is not
# stated answers ``loads_from_folders`` null, and a game's folder outside every
# scanned folder answers ``content_folder_scanned`` false; each is read off the
# field rather than off its note.
_SAID_BY_THE_FIELDS = frozenset({CAVEAT_EXTRA_CONTENT_FOLDERS_UNSTATED, CAVEAT_CONTENT_OUTSIDE_EXTRA_CONTENT_FOLDERS})


def read_extra_content(answer: Any) -> ExtraContentFolders:
    """*answer* in Tender's words."""
    if answer.loads_from_folders is not True:
        return NOT_OFFERED
    folders = tuple(answer.folders)
    scanned = answer.content_folder_scanned
    beside_launch = any(caveat.code == CAVEAT_EXTRA_CONTENT_SCANNED_BESIDE_LAUNCH for caveat in answer.caveats)
    only_beside_launch = (
        scanned is True and beside_launch and not any(folder.registered_before_launch is True for folder in folders)
    )
    extensions = tuple(dict.fromkeys(extension for folder in folders for extension in folder.extensions))
    return ExtraContentFolders(
        offered=True,
        game_folder_scanned=scanned,
        only_beside_launch=only_beside_launch,
        extensions=extensions,
    )


class AtlasExtraContentAdapter:
    """Asks a game's answering emulator source about extra content in folders, and reads it into Tender's view.

    Keeps no answer of its own: each is asked through a reading of the emulator
    sources and kept by that reading alone.
    """

    def __init__(self, *, sources: EmulatorSourcesAdapter, log_debug: Callable[[str], None]) -> None:
        self._sources = sources
        self._log_debug = log_debug

    def extra_content_folders(
        self,
        system: str,
        *,
        label: str | None,
        content_path: str | None,
        reading: SourcesReading | None = None,
    ) -> ExtraContentFolders:
        """Whether *system*'s entry *label* names loads extra content from folders, about the game at *content_path*.

        *label* chooses the entry the game starts with, ``None`` the frontend's
        first; *content_path* is the game's folder, absolute, or ``None`` to ask
        about no game. Where no source answers or the resolver could not be
        asked, nothing is offered.
        """
        reading = reading if reading is not None else self._sources.read()
        installation = reading.answering_installation(system)
        if installation is None:
            self._log_debug(f"[extra content] no emulator source answers ({reading.no_answer_reason()})")
            return NOT_OFFERED

        def ask() -> Any:
            try:
                return installation.extra_content_folders(system, label=label, content_path=content_path)
            except Exception as exc:
                self._log_debug(f"[extra content] resolver failed on extra_content_folders({system!r}): {exc!r}")
                return None

        answer = reading.remember(("extra_content_folders", system, label, content_path), ask)
        if answer is None:
            return NOT_OFFERED
        codes = sorted({caveat.code for caveat in answer.caveats} - _SAID_BY_THE_FIELDS)
        self._log_debug(
            f"[extra content] {system}/{label}: loads={answer.loads_from_folders} "
            f"scanned={answer.content_folder_scanned} caveats={codes}"
        )
        return read_extra_content(answer)
