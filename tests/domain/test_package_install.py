"""The rules Tender applies to a package install: the one game it records, the bound its removal keeps, the verdict."""

from __future__ import annotations

from domain.launchability import NEEDS_INSTALLING, NOT_A_LAUNCH_FILE, STARTS, Launchability
from domain.package_install import (
    COMMAND_INCOMPLETE,
    SEVERAL_GAMES,
    InstalledTitle,
    PackageGameTarget,
    PackageInstallRefused,
    drive_game_folder,
    installed_title,
    package_installed_verdict,
)

_DRIVE = "/home/deck/.var/app/net.retrodeck.retrodeck/config/rpcs3/dev_hdd0"
_GAME = PackageGameTarget(
    f"{_DRIVE}/game/NPUB30000", f"{_DRIVE}/game/NPUB30000/USRDIR/EBOOT.BIN", "/var/x/game/NPUB30000/USRDIR/EBOOT.BIN"
)


class TestTheInstalledTitle:
    def test_no_game_target_is_no_title(self):
        assert installed_title(()) is None

    def test_a_game_and_its_patch_in_one_folder_are_one_title(self):
        patch = PackageGameTarget(_GAME.folder, None, None)

        assert installed_title((_GAME, patch)) == InstalledTitle(
            f"{_DRIVE}/game/NPUB30000",
            f"{_DRIVE}/game/NPUB30000/USRDIR/EBOOT.BIN",
            "/var/x/game/NPUB30000/USRDIR/EBOOT.BIN",
        )

    def test_two_folders_are_several_games(self):
        other = PackageGameTarget(f"{_DRIVE}/game/BLUS00001", "/b/EBOOT.BIN", "/b/EBOOT.BIN")

        assert installed_title((_GAME, other)) == PackageInstallRefused(SEVERAL_GAMES)

    def test_a_title_not_placed_on_the_host_cannot_be_checked(self):
        unplaced = PackageGameTarget(_GAME.folder, None, _GAME.boot_file_in_emulator)

        assert installed_title((unplaced,)) == PackageInstallRefused(COMMAND_INCOMPLETE)


class TestTheDrivesGameFolder:
    def test_a_title_folder_is_bounded_by_the_game_folder_it_lies_in(self):
        assert drive_game_folder(f"{_DRIVE}/game/NPUB30000") == f"{_DRIVE}/game"
        assert drive_game_folder(f"{_DRIVE}/game/NPUB30000/") == f"{_DRIVE}/game"

    def test_a_folder_outside_a_game_folder_has_no_bound(self):
        assert drive_game_folder(f"{_DRIVE}/home/00000001/savedata/NPUB30000-SAVE") is None
        assert drive_game_folder(f"{_DRIVE}/home") is None
        assert drive_game_folder("/home/deck/retrodeck/roms/ps3/Game") is None

    def test_the_game_folder_itself_or_an_unplain_name_has_no_bound(self):
        assert drive_game_folder(f"{_DRIVE}/game") is None
        assert drive_game_folder(f"{_DRIVE}/game/..") is None
        assert drive_game_folder(f"{_DRIVE}/game/Some Game") is None
        assert drive_game_folder("") is None


def _verdict(state: str) -> Launchability:
    return Launchability(
        state=state,
        entry="RPCS3 Directory (Standalone)",
        system="ps3",
        file="EBOOT.BIN",
        extension=".bin",
        starts_from=(".iso", ".ps3"),
    )


class TestTheVerdict:
    def test_a_refusal_by_the_accept_list_alone_starts(self):
        verdict = package_installed_verdict(_verdict(NOT_A_LAUNCH_FILE))

        assert verdict.state == STARTS
        assert verdict.starts_from == ()

    def test_every_other_verdict_stands(self):
        verdict = _verdict(NEEDS_INSTALLING)

        assert package_installed_verdict(verdict) is verdict
