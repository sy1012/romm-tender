"""Tender's reading of a package install is the resolver's answer, on every recorded machine that asks it.

Each vector in ``tests/adapters/atlas_vectors/`` whose expectations hold a
``package_install_command`` answer is asked its own question live, through the
real resolver, and that answer is read through Tender's reading module
(:func:`adapters.atlas_package_install.read_package_install`). The recorded
machines state no distribution environment, so their commands are ones Tender
does not run as stated; the same answers with one stated show the install the
reading plans.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from _atlas_machines import fixture_machine, select, vectors_asking
from _vendor import atlas

from adapters.atlas_package_install import AtlasPackageInstallAdapter, read_package_install
from adapters.emulator_sources import EmulatorSourcesAdapter
from domain.package_install import COMMAND_INCOMPLETE, SEVERAL_GAMES, PackageInstallPlan, PackageInstallRefused

_VECTORS = vectors_asking("package_install_command")
_NAMED = {vector["name"]: vector for _stem, vector in _VECTORS}


def _asked(vector: dict[str, Any]) -> Any:
    inp = vector["input"]
    query = inp["package_install_query"]
    installation = select(atlas.detect(inp["home"], fixture_machine(inp)), query.get("installation"))
    return installation.package_install_command(query["system"], query["content_path"], label=query.get("label"))


def _with_environment(answer: Any) -> Any:
    """*answer* with its command's distribution environment stated, as a pinned RetroDECK states it."""
    return dataclasses.replace(answer, command=dataclasses.replace(answer.command, distribution_environment=()))


def test_the_copy_holds_machines_that_ask_it():
    assert len(_VECTORS) == 9


@pytest.mark.parametrize(("stem", "vector"), _VECTORS, ids=[v["name"] for _s, v in _VECTORS])
def test_a_command_tender_cannot_run_as_stated_installs_nothing(stem: str, vector: dict[str, Any]) -> None:
    recorded = vector["expected"]["package_install_command"]
    games = [t for t in recorded["package_targets"] if t["destination"] == "package-game-folder"]
    unread = [t for t in recorded["package_targets"] if t["destination"] == "package-destination-unread"]

    view = read_package_install(_asked(vector))

    if recorded["command"] is None or (not games and not unread):
        assert view is None, stem
    else:
        assert isinstance(view, PackageInstallRefused), stem
        assert view.reason == COMMAND_INCOMPLETE
        assert view.installer == "RPCS3"


class TestTheInstallItPlans:
    def test_a_folder_of_a_game_and_its_licence_installs_the_game_from_the_folder(self):
        vector = _NAMED["package-install-rpcs3-installs-a-folder-of-packages"]
        recorded = vector["expected"]["package_install_command"]
        game = next(t for t in recorded["package_targets"] if t["destination"] == "package-game-folder")

        plan = read_package_install(_with_environment(_asked(vector)), writable=("/home/deck/retrodeck/roms/ps3/Game",))

        assert isinstance(plan, PackageInstallPlan)
        assert plan.title.folder == game["install_folder"]["host_path"]
        assert plan.title.boot_file == game["boot_file"]["host_path"]
        assert plan.title.boot_file_in_emulator == game["boot_file"]["frontend_path"]
        assert plan.title.boot_file.endswith("/dev_hdd0/game/NPUB30000/USRDIR/EBOOT.BIN")
        assert plan.installer == "RPCS3"
        assert plan.argv[:3] == ("flatpak", "run", "--nosocket=wayland")
        assert "--filesystem=/home/deck/retrodeck/roms/ps3/Game" in plan.argv
        assert plan.argv[-3:] == ("--headless", "--installpkg", "/home/deck/retrodeck/roms/ps3/Game")
        assert "--no-gui" not in plan.argv

    def test_one_package_installs_its_game(self):
        plan = read_package_install(_with_environment(_asked(_NAMED["package-install-rpcs3-installs-one-package"])))

        assert isinstance(plan, PackageInstallPlan)
        assert plan.argv[-2] == "--installpkg"

    def test_a_drive_that_is_not_established_places_no_game_to_check(self):
        vector = _NAMED["package-install-an-unreadable-vfs-configuration-states-no-folder"]

        view = read_package_install(_with_environment(_asked(vector)))

        assert view == PackageInstallRefused(COMMAND_INCOMPLETE, "RPCS3")

    def test_a_package_whose_destination_is_unread_beside_no_game_refuses(self):
        vector = _NAMED["package-install-a-package-whose-metadata-is-unread-states-no-folder"]

        view = read_package_install(_with_environment(_asked(vector)))

        assert view == PackageInstallRefused(COMMAND_INCOMPLETE, "RPCS3")

    def test_a_file_that_is_no_package_is_nothing_to_install(self):
        vector = _NAMED["package-install-a-file-that-is-no-package-takes-nothing"]

        assert read_package_install(_with_environment(_asked(vector))) is None

    def test_packages_of_two_games_are_refused(self):
        answer = _with_environment(_asked(_NAMED["package-install-rpcs3-installs-a-folder-of-packages"]))
        game = next(t for t in answer.package_targets if t.destination == atlas.PACKAGE_DESTINATION_GAME_FOLDER)
        other = dataclasses.replace(
            game,
            install_folder=atlas.PackageInstallPath("/elsewhere/game/BLUS00001", "/elsewhere/game/BLUS00001"),
        )

        view = read_package_install(dataclasses.replace(answer, package_targets=(game, other)))

        assert view == PackageInstallRefused(SEVERAL_GAMES, "RPCS3")


class _Answering:
    def __init__(self, answer: Any = None, raises: Exception | None = None) -> None:
        self.kind = "retrodeck"
        self._answer = answer
        self._raises = raises
        self.asked: list[tuple[str, str]] = []

    def package_install_command(self, system: str, content_path: str, *, label: str | None = None) -> Any:
        self.asked.append((system, content_path))
        if self._raises is not None:
            raise self._raises
        return self._answer


def _adapter(installations: list[Any]) -> AtlasPackageInstallAdapter:
    return AtlasPackageInstallAdapter(
        sources=EmulatorSourcesAdapter(
            user_home="/home/deck",
            settings={},
            log_debug=lambda _line: None,
            detect_installations=lambda home, machine: installations,
            machine=object(),
        ),
        log_debug=lambda _line: None,
    )


class TestTheAdapter:
    def test_it_asks_the_source_answering_the_system_with_the_downloads_path(self):
        answer = _with_environment(_asked(_NAMED["package-install-rpcs3-installs-one-package"]))
        installation = _Answering(answer)

        plan = _adapter([installation]).package_install("ps3", "/roms/ps3/G.pkg", writable=("/roms/ps3",))

        assert installation.asked == [("ps3", "/roms/ps3/G.pkg")]
        assert isinstance(plan, PackageInstallPlan)

    def test_no_source_is_nothing_to_install(self):
        assert _adapter([]).package_install("ps3", "/roms/ps3/G") is None

    def test_a_resolver_that_raises_is_nothing_to_install(self):
        assert _adapter([_Answering(raises=RuntimeError("boom"))]).package_install("ps3", "/roms/ps3/G") is None
