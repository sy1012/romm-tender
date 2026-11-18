"""Installing a downloaded package into its emulator, in Tender's words: the plan and the title it leaves.

The resolver states the install (:mod:`adapters.atlas_package_install` reads
it); this is the value it is read into and the rules Tender applies to it. A
game whose download is a package is installed into the emulator's own drive,
and its install record then points at the installed title rather than at the
download (ADR-0051).

Pure compute — no I/O.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

from domain.launchability import NOT_A_LAUNCH_FILE, STARTS, Launchability

# Why no install is run for a download whose content is a package, in Tender's
# words: the resolver gives a command Tender cannot run, or places no game it
# could check, or the packages install more than one game, which one install
# record cannot hold.
COMMAND_INCOMPLETE = "command_incomplete"
SEVERAL_GAMES = "several_games"
# Why an install that ran did not install the game: it did not end, it could
# not be started, or it ended and no game's boot file stands.
DID_NOT_FINISH = "did_not_finish"
NOT_STARTED = "not_started"
NO_BOOT_FILE = "no_boot_file"

# The folder RPCS3 installs every game into on its drive, ``<dev_hdd0>/game/<folder>``
# (``package_reader::set_install_path``, ``rpcs3/Crypto/unpkg.cpp:860-919`` at d5213de6).
_GAME_FOLDER = "game"
# The characters RPCS3 spells an install folder with; ``vfs::escape`` may change any other.
_PLAIN_FOLDER = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


@dataclass(frozen=True, slots=True)
class InstalledTitle:
    """The game a package install leaves: its folder and boot file on the host, and the boot file in the emulator."""

    folder: str
    boot_file: str
    boot_file_in_emulator: str


@dataclass(frozen=True, slots=True)
class PackageInstallPlan:
    """The install to run: its command as Tender runs it, the game it installs, and the emulator that installs it."""

    argv: tuple[str, ...]
    title: InstalledTitle
    installer: str | None


@dataclass(frozen=True, slots=True)
class PackageInstallRefused:
    """Why a download whose content is a package is not installed; ``reason`` is one of this module's words."""

    reason: str
    installer: str | None = None


@dataclass(frozen=True, slots=True)
class PackageGameTarget:
    """One package the install puts into a game's folder; a path is ``None`` where the reading did not place it."""

    folder: str | None
    boot_file: str | None
    boot_file_in_emulator: str | None


# The files RPCS3's installer takes from a folder it is handed: packages and the
# licences installed with them (main_window::InstallPackages at d5213de6). It
# lists that folder alone and never looks into one below it.
_PACKAGE_SUFFIXES = (".pkg", ".rap", ".edat")


def package_folder(files: list[str], download_folder: str) -> str:
    """The folder to hand the installer: the one folder holding every package and licence of a download.

    *files* are the download's files, at any depth. A RomM game can keep its
    packages one folder below the game's own, beside files of its own (a
    playlist), and the installer reads only the folder it is handed, so the
    folder they lie in is the one. Where they lie in more than one folder, or
    there are none, *download_folder* is answered and the resolver says what
    it takes from it.
    """
    folders = {os.path.dirname(path) for path in files if path.lower().endswith(_PACKAGE_SUFFIXES)}
    return folders.pop() if len(folders) == 1 else download_folder


def installed_title(targets: tuple[PackageGameTarget, ...]) -> InstalledTitle | PackageInstallRefused | None:
    """The one game *targets* install, or why there is none to record; ``None`` where they install no game.

    A patch or an add-on installs into its game's folder, so every target in
    one folder is one game. Targets in more than one folder are several games,
    and one whose folder or boot file is not placed on the host is a game
    Tender could not check or record.
    """
    if not targets:
        return None
    folders = {target.folder for target in targets}
    if len(folders) > 1:
        return PackageInstallRefused(SEVERAL_GAMES)
    target = targets[0]
    if target.folder is None or target.boot_file is None or target.boot_file_in_emulator is None:
        return PackageInstallRefused(COMMAND_INCOMPLETE)
    return InstalledTitle(target.folder, target.boot_file, target.boot_file_in_emulator)


def drive_game_folder(title_folder: str) -> str | None:
    """The emulator drive's game folder that *title_folder* lies in, which bounds the title's removal, or ``None``.

    ``None`` unless *title_folder* is a folder of plain name directly inside a
    folder named ``game`` — the only place a package install puts a game — so
    a removal held to this bound can never reach the drive's user folders,
    where the saves lie.
    """
    folder = os.path.normpath(title_folder)
    name = os.path.basename(folder)
    parent = os.path.dirname(folder)
    if not name or not set(name) <= _PLAIN_FOLDER or os.path.basename(parent) != _GAME_FOLDER:
        return None
    return parent


def package_installed_verdict(verdict: Launchability) -> Launchability:
    """*verdict* for a game installed from a package, whose start does not rest on the system's accept-list.

    The accept-list is what ES-DE scans a ROM folder with, and an installed
    title is no ROM it scans: an entry refused only by the list starts it as
    far as Tender asks, and whether a command stands is the launch command's
    answer. Every other verdict stands as it is.
    """
    if verdict.state != NOT_A_LAUNCH_FILE:
        return verdict
    return dataclasses.replace(verdict, state=STARTS, starts_from=())
