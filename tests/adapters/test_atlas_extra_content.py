"""Tests for the atlas extra-content adapter — the resolver's answer on updates and add-ons in Tender's view.

Answers are built from the resolver's own value objects, so a field renamed
upstream fails here rather than passing against a stand-in.
``tests/adapters/test_extra_content_vectors.py`` runs every recorded machine
that asks the question through the same reading.
"""

from __future__ import annotations

from typing import Any

from _vendor.atlas import (
    CAVEAT_CONTENT_OUTSIDE_EXTRA_CONTENT_FOLDERS,
    CAVEAT_EXTRA_CONTENT_FOLDERS_UNSTATED,
    CAVEAT_EXTRA_CONTENT_SCANNED_BESIDE_LAUNCH,
    ExtraContentAnswer,
    ExtraContentFolder,
)
from _vendor.atlas.placement import Caveat

from adapters.atlas_extra_content import AtlasExtraContentAdapter, read_extra_content
from adapters.emulator_sources import EmulatorSourcesAdapter
from domain.extra_content import NOT_OFFERED, ExtraContentFolders

_EXTENSIONS = (".nsp", ".xci")
_GAME = "/home/deck/retrodeck/roms/switch/Zelda"


def _caveat(code: str) -> Caveat:
    return Caveat(code, "said", {})


def _external(path: str = "/home/deck/retrodeck/roms/switch") -> ExtraContentFolder:
    return ExtraContentFolder(path, True, True, _EXTENSIONS)


def _game_dir(path: str = "/home/deck/retrodeck/roms/switch") -> ExtraContentFolder:
    return ExtraContentFolder(path, False, None, _EXTENSIONS)


def _answer(
    loads: bool | None = True,
    folders: tuple[ExtraContentFolder, ...] = (),
    scanned: bool | None = None,
    caveats: tuple[Caveat, ...] = (),
) -> ExtraContentAnswer:
    return ExtraContentAnswer(
        loads_from_folders=loads, folders=folders, content_folder_scanned=scanned, caveats=caveats
    )


class TestTheReading:
    def test_an_entry_that_loads_from_an_external_folder_holding_the_game_is_offered_with_nothing_in_the_way(self):
        view = read_extra_content(_answer(folders=(_external(),), scanned=True))

        assert view == ExtraContentFolders(offered=True, game_folder_scanned=True, extensions=_EXTENSIONS)

    def test_an_unstated_entry_offers_nothing(self):
        view = read_extra_content(_answer(loads=None, caveats=(_caveat(CAVEAT_EXTRA_CONTENT_FOLDERS_UNSTATED),)))

        assert view == NOT_OFFERED

    def test_a_stated_no_offers_nothing(self):
        assert read_extra_content(_answer(loads=False)) == NOT_OFFERED

    def test_a_game_folder_outside_every_scanned_folder_says_so(self):
        view = read_extra_content(
            _answer(
                folders=(_external("/home/deck/switch-extras"),),
                scanned=False,
                caveats=(_caveat(CAVEAT_CONTENT_OUTSIDE_EXTRA_CONTENT_FOLDERS),),
            )
        )

        assert view.offered is True
        assert view.game_folder_scanned is False

    def test_a_game_folder_scanned_beside_the_launch_is_offered_with_nothing_in_the_way(self):
        view = read_extra_content(
            _answer(
                folders=(_game_dir(),),
                scanned=True,
                caveats=(_caveat(CAVEAT_EXTRA_CONTENT_SCANNED_BESIDE_LAUNCH),),
            )
        )

        assert view == ExtraContentFolders(offered=True, game_folder_scanned=True, extensions=_EXTENSIONS)

    def test_the_extensions_are_every_folder_s_once_in_order(self):
        view = read_extra_content(
            _answer(folders=(_external(), ExtraContentFolder("/x", False, None, (".xci", ".nsp"))), scanned=True)
        )

        assert view.extensions == (".nsp", ".xci")

    def test_no_folders_know_no_extensions(self):
        assert read_extra_content(_answer(scanned=False)).extensions == ()


class _Installation:
    def __init__(self, answer: ExtraContentAnswer | Exception, *, kind: str = "retrodeck") -> None:
        self.kind = kind
        self._answer = answer
        self.calls: list[tuple[str, str | None, str | None]] = []

    def emulators_for(self, system: str, *, content_path: str | None = None) -> Any:
        from types import SimpleNamespace

        from _vendor.atlas import AVAILABILITY_STARTABLE

        entries = (SimpleNamespace(availability=AVAILABILITY_STARTABLE),) if system == "switch" else ()
        return SimpleNamespace(entries=entries, caveats=())

    def extra_content_folders(
        self, system: str, *, label: str | None = None, content_path: str | None = None
    ) -> ExtraContentAnswer:
        self.calls.append((system, label, content_path))
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _adapter(installations: list[Any], traces: list[str]) -> AtlasExtraContentAdapter:
    return AtlasExtraContentAdapter(
        sources=EmulatorSourcesAdapter(
            user_home="/home/deck",
            settings={},
            log_debug=traces.append,
            detect_installations=lambda home, machine: list(installations),
            machine=object(),
        ),
        log_debug=traces.append,
    )


class TestTheAdapter:
    def test_it_asks_the_source_answering_the_system_with_the_entry_and_the_game_s_folder(self):
        installation = _Installation(_answer(folders=(_external(),), scanned=True))

        view = _adapter([installation], []).extra_content_folders("switch", label="Eden (AppImage)", content_path=_GAME)

        assert view.offered is True
        assert installation.calls == [("switch", "Eden (AppImage)", _GAME)]

    def test_one_reading_asks_each_question_once(self):
        installation = _Installation(_answer())
        adapter = _adapter([installation], [])
        reading = adapter._sources.read()  # pyright: ignore[reportPrivateUsage]

        adapter.extra_content_folders("switch", label=None, content_path=None, reading=reading)
        adapter.extra_content_folders("switch", label=None, content_path=None, reading=reading)

        assert len(installation.calls) == 1

    def test_with_no_source_answering_nothing_is_offered(self):
        traces: list[str] = []

        assert _adapter([], traces).extra_content_folders("switch", label=None, content_path=None) == NOT_OFFERED
        assert any("no emulator source answers" in line for line in traces)

    def test_a_resolver_that_raises_offers_nothing_and_is_traced(self):
        traces: list[str] = []

        view = _adapter([_Installation(RuntimeError("boom"))], traces).extra_content_folders(
            "switch", label=None, content_path=None
        )

        assert view == NOT_OFFERED
        assert any("resolver failed on extra_content_folders" in line for line in traces)
