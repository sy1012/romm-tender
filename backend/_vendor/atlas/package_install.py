"""What installing a PS3 package into RPCS3 does, read from RPCS3's own install — and the answer that states it.

Every citation is at RPCS3 d5213de6, the build RetroDECK ships and the RPCS3
save card pins. ``rpcs3 --headless --installpkg <path>`` starts a headless
application (``create_application``, ``rpcs3/rpcs3.cpp:443-451``), whose
emulator runs as user ``00000001`` unless ``--user-id`` names another
(``headless_application::Init``, ``rpcs3/rpcs3qt/headless_application.cpp:31``;
``rpcs3.cpp:938-947``, :987-989). It hands the path to
``main_window::InstallPackages`` with no window and returns ``0`` whatever came
of the install (``rpcs3.cpp:1146-1187``), so the exit status states nothing; a
caller checks what the install leaves. ``--no-gui`` beside it is a fatal error
(:1150-1153).

``InstallPackages`` (``rpcs3/rpcs3qt/main_window.cpp:818-936``):

1. A path naming a directory is replaced by the files directly in it — not
   its subfolders, not its hidden files — sorted by name, case aside
   (``gui::utils::get_dir_entries``, ``rpcs3/rpcs3qt/qt_utils.cpp:170-179``,
   over a ``QDir`` and its default sort).
2. Every path containing ``.rap``, then every one containing ``.edat`` — case
   aside, anywhere in the absolute path, which is what ``QStringList::filter``
   over ``.*\\.rap`` matches — is copied into the user's
   ``dev_hdd0/home/<user>/exdata`` (``install_filetype``, :868-905;
   ``InstallFileInExData``, :778-816).
3. Every path containing ``.pkg``, the same way, is a package; each one
   ``package_reader`` takes is installed in turn and an invalid one is skipped
   (``HandlePackageInstallation``, :939-1000). The first package that fails
   ends the install; the ones before it stay (``package_reader::extract_data``,
   ``rpcs3/Crypto/unpkg.cpp:1442-1560``).

Where one package goes is ``package_reader::set_install_path``
(unpkg.cpp:860-919), by the content type its metadata states: a licence
(``0x0B``) into ``home/<user>/exdata/``; a theme, widget, VSH module, PSN
avatar or virtual memory card somewhere of its own; anything else into
``game/<install dir>/``, the install dir being the nine bytes at offset 55 of
the header or the directory an install-directory packet names in their place
(:249-253, :423-436), refused where it leaves its folder. A game's executable
is written as ``<that folder>/USRDIR/EBOOT.BIN`` (:1412-1416). Whether a
package carries one lies in its encrypted file table, which atlas does not
open — a patch or an add-on goes into the same folder as the game it belongs
to and carries none.
"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from .launch import PROBE_HIT, PROBE_UNKNOWN
from .launch_command import CommandView
from .machine import PS3_TITLE_OK, Ps3TitleResult
from .placement import Caveat
from .ps3_title import SOURCE_PKG

PackageDestination = Literal[
    "package-game-folder", "package-licence-folder", "package-elsewhere", "package-destination-unread"
]
DESTINATION_GAME_FOLDER: PackageDestination = "package-game-folder"
"""The package installs into a game's folder below the emulator's drive — a game, its patch or its add-on."""
DESTINATION_LICENCE_FOLDER: PackageDestination = "package-licence-folder"
"""The package is a licence, and installs into the user's licence folder."""
DESTINATION_ELSEWHERE: PackageDestination = "package-elsewhere"
"""The package installs somewhere that is no game's folder and no licence folder: a theme, a widget, an avatar."""
DESTINATION_UNREAD: PackageDestination = "package-destination-unread"
"""Where the package installs is not established — its header or metadata was not read, or names no folder."""
PACKAGE_DESTINATIONS: tuple[PackageDestination, ...] = (
    DESTINATION_GAME_FOLDER,
    DESTINATION_LICENCE_FOLDER,
    DESTINATION_ELSEWHERE,
    DESTINATION_UNREAD,
)

# The entry's emulator has no package installer atlas reads: no command is
# stated. ``data`` names the ``installation`` and, where one was chosen, the
# ``entry``'s label.
CAVEAT_PACKAGE_INSTALL_UNSTATED: Final = "package-install-unstated"
# The path names nothing the installer takes as a package: the install runs
# and installs nothing. ``data`` names the ``path``.
CAVEAT_PACKAGE_INSTALL_TAKES_NOTHING: Final = "package-install-takes-nothing"
# What lies at the path, or in it, cannot be told, so which packages the
# install takes is not established. ``data`` names the ``path``.
CAVEAT_PACKAGE_INSTALL_PATH_UNREAD: Final = "package-install-path-unread"
# One package's header or metadata could not be read, so where it installs is
# not established. ``data`` names the ``package``.
CAVEAT_PACKAGE_HEADER_UNREAD: Final = "package-header-unread"
# The emulator's internal drive is not established, so no folder an install
# writes is stated.
CAVEAT_PACKAGE_DRIVE_UNRESOLVED: Final = "package-drive-unresolved"
# The install writes licences for the user the headless installer runs as,
# and a launch reads them for the user the emulator's own settings make
# current, which atlas does not read: where the drive holds an account
# besides that one, the two may differ. ``data`` names the ``account`` the
# install writes for and the ``accounts`` found.
CAVEAT_PACKAGE_LICENCE_ACCOUNT: Final = "package-licence-account"

HEADLESS_ACCOUNT: Final = "00000001"
_SOURCE = "RPCS3 d5213de6"
_HEADLESS = "--headless"
_INSTALL = "--installpkg"
_BOOT_FILE = "USRDIR/EBOOT.BIN"
_CONTENT_TYPE_LICENSE = 0x0B
# set_install_path's other destinations of their own (unpkg.cpp:874-897):
# theme, widget, VSH module, PSN avatar, virtual memory card.
_CONTENT_TYPES_ELSEWHERE = frozenset((0x09, 0x0A, 0x0C, 0x0D, 0x11))
# The characters a product code or a DLC folder is spelled with; a name of any
# other is one vfs::escape may change, which this reading does not follow.
_PLAIN_FOLDER = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


@dataclass(frozen=True, slots=True)
class PackageInstallPath:
    """A path an install writes, in both spellings."""

    frontend_path: str
    """The path as the emulator spells it — inside its sandbox for RetroDECK, the spelling a launch command is
    handed."""
    host_path: str | None
    """The same path as the host spells it; ``null`` where atlas cannot place it."""


@dataclass(frozen=True, slots=True)
class PackageInstallTarget:
    """One package the install takes, in the order it installs them, and where it puts it."""

    package: str
    """The package file, as the emulator spells it."""
    title_id: str | None
    """The title id its header states — the nine bytes at offset 55, as stated; ``null`` where the header was not
    read."""
    content_type: int | None
    """The content type its metadata states, ``0`` where it states none; ``null`` where the metadata was not read."""
    destination: PackageDestination
    """Where it installs: one of :data:`PACKAGE_DESTINATIONS`."""
    install_folder: PackageInstallPath | None
    """The folder it installs into — a game's folder or the licence folder; ``null`` on every other destination,
    and where the emulator's drive is not established."""
    boot_file: PackageInstallPath | None
    """``<install_folder>/USRDIR/EBOOT.BIN``, where the emulator writes the game's executable if the package carries
    one — on a game-folder destination alone. Its presence after the install is the one sign the game installed."""


def install_arguments(path: str) -> tuple[str, ...]:
    """RPCS3's arguments installing *path*, a package or a directory of them: ``--headless --installpkg <path>``."""
    return (_HEADLESS, _INSTALL, path)


@dataclass(frozen=True, slots=True)
class PackageReading:
    """What the install takes from one path and where each package goes."""

    targets: tuple[PackageInstallTarget, ...]
    licence_files: tuple[str, ...]
    licence_folder: PackageInstallPath | None
    sources: tuple[str, ...]
    caveats: tuple[Caveat, ...]


def _contains(path: str, suffix: str) -> bool:
    """``QStringList::filter`` over ``.*\\.<suffix>``, case aside: the text anywhere in the absolute path."""
    return f".{suffix}" in path.lower()


class _Reading:
    def __init__(self, view: CommandView, read_title: Callable[[str], Ps3TitleResult], drive: str | None) -> None:
        self._view = view
        self._read_title = read_title
        self._drive = drive.rstrip("/") if drive else None

    def place(self, *parts: str) -> PackageInstallPath | None:
        if self._drive is None:
            return None
        path = posixpath.join(self._drive, *parts)
        return PackageInstallPath(path, self._view.host_path(path))

    def files(self, path: str) -> tuple[str, ...] | Caveat:
        """The paths ``InstallPackages`` works through for *path*: a directory's files, or *path* itself."""
        directory = self._view.is_directory(path)
        if directory == PROBE_UNKNOWN:
            return self._unread(path)
        if directory != PROBE_HIT:
            return (path,)
        names = self._view.listing(path)
        if names is None:
            return self._unread(path)
        found: list[str] = []
        for name in sorted((n for n in names if not n.startswith(".")), key=lambda n: (n.lower(), n)):
            candidate = posixpath.join(path, name)
            probe = self._view.regular_file(candidate)
            if probe == PROBE_UNKNOWN:
                return self._unread(candidate)
            if probe == PROBE_HIT:
                found.append(candidate)
        return tuple(found)

    @staticmethod
    def _unread(path: str) -> Caveat:
        return Caveat(
            CAVEAT_PACKAGE_INSTALL_PATH_UNREAD,
            f"what lies at {path} cannot be told, so which packages RPCS3 installs from it is not established",
            {"path": path},
        )

    def target(self, package: str) -> tuple[PackageInstallTarget, tuple[Caveat, ...]]:
        host = self._view.host_path(package)
        result = self._read_title(host) if host is not None else None
        facts = result.facts if result is not None and result.status == PS3_TITLE_OK else None
        if facts is None or facts.source != SOURCE_PKG or facts.content_type is None:
            title = facts.title_id if facts is not None and facts.source == SOURCE_PKG else None
            return PackageInstallTarget(package, title, None, DESTINATION_UNREAD, None, None), (
                Caveat(
                    CAVEAT_PACKAGE_HEADER_UNREAD,
                    f"{package}'s package header or metadata was not read, so where RPCS3 installs it is not "
                    "established — and whether RPCS3 takes it at all",
                    {"package": package},
                ),
            )
        content_type = facts.content_type
        if content_type == _CONTENT_TYPE_LICENSE:
            folder = self.place("home", HEADLESS_ACCOUNT, "exdata")
            return PackageInstallTarget(
                package, facts.title_id, content_type, DESTINATION_LICENCE_FOLDER, folder, None
            ), ()
        if content_type in _CONTENT_TYPES_ELSEWHERE:
            return PackageInstallTarget(package, facts.title_id, content_type, DESTINATION_ELSEWHERE, None, None), ()
        name = facts.install_dir if facts.install_dir is not None else facts.title_id
        if not name or not set(name) <= _PLAIN_FOLDER:
            return PackageInstallTarget(package, facts.title_id, content_type, DESTINATION_UNREAD, None, None), (
                Caveat(
                    CAVEAT_PACKAGE_HEADER_UNREAD,
                    f"{package} names its install folder {name!r}, which RPCS3 refuses or escapes "
                    "(set_install_path, unpkg.cpp:902-912) — where it installs is not followed here",
                    {"package": package},
                ),
            )
        folder = self.place("game", name)
        boot = None if folder is None else self.place("game", name, _BOOT_FILE)
        return PackageInstallTarget(package, facts.title_id, content_type, DESTINATION_GAME_FOLDER, folder, boot), ()


def read_packages(
    path: str, view: CommandView, read_title: Callable[[str], Ps3TitleResult], drive: str | None
) -> PackageReading:
    """What ``rpcs3 --headless --installpkg <path>`` takes from *path* and where it puts each package.

    *path* is the emulator's spelling, every probe goes through *view* — the
    frontend's, which is RPCS3's wherever these arrangements run it — and
    *read_title* reads a package's header on the host. *drive* is RPCS3's
    ``dev_hdd0`` in its own spelling, ``None`` where it is not established.
    """
    reading = _Reading(view, read_title, drive)
    files = reading.files(path)
    if isinstance(files, Caveat):
        return PackageReading((), (), reading.place("home", HEADLESS_ACCOUNT, "exdata"), (), (files,))
    licences = tuple(f for f in files if _contains(f, "rap")) + tuple(f for f in files if _contains(f, "edat"))
    packages = tuple(f for f in files if _contains(f, "pkg"))
    caveats: list[Caveat] = []
    targets: list[PackageInstallTarget] = []
    for package in packages:
        target, notes = reading.target(package)
        targets.append(target)
        caveats.extend(notes)
    if not packages:
        caveats.append(
            Caveat(
                CAVEAT_PACKAGE_INSTALL_TAKES_NOTHING,
                f"RPCS3 installs every file whose path contains .pkg, case aside, and nothing at {path} does "
                "(InstallPackages, main_window.cpp:913-919) — the install installs no package",
                {"path": path},
            )
        )
    if drive is None:
        caveats.append(
            Caveat(
                CAVEAT_PACKAGE_DRIVE_UNRESOLVED,
                "where RPCS3's internal drive is cannot be told, so no folder the install writes is stated",
                {},
            )
        )
    sources = (
        f"RPCS3 runs the install headless and exits 0 whatever came of it (rpcs3.cpp:443-451, :1146-1187; "
        f"{_SOURCE}): check the boot file each game package states",
        "a directory is replaced by the files directly in it, sorted by name; .rap and .edat files are copied into "
        f"user {HEADLESS_ACCOUNT}'s exdata, then every .pkg is installed in turn, the first failure ending the "
        "install (InstallPackages, main_window.cpp:818-936; headless_application.cpp:31; extract_data, "
        "unpkg.cpp:1442-1560)",
        "a package installs where its content type says: a licence into exdata, a theme, widget, VSH module, "
        "avatar or memory card somewhere of its own, anything else into game/<the header's title id or the "
        "install directory its metadata names>, its executable as USRDIR/EBOOT.BIN there "
        "(set_install_path, unpkg.cpp:860-919; read_metadata, :249-253, :423-436; :1412-1416)",
    )
    return PackageReading(
        tuple(targets), licences, reading.place("home", HEADLESS_ACCOUNT, "exdata"), sources, tuple(caveats)
    )


def licence_account_caveat(accounts: tuple[str, ...] | None) -> Caveat | None:
    """``package-licence-account`` where the drive holds an account besides the installer's — or that is unknown.

    *accounts* are the accounts found on the drive, ``None`` where they could
    not be listed. A drive with none, or with the installer's alone, needs no
    caveat: RPCS3's own settings name ``00000001`` until a user picks another
    (``gui_application::Init``, ``rpcs3/rpcs3qt/gui_application.cpp:297-307``).
    """
    if accounts is not None and set(accounts) <= {HEADLESS_ACCOUNT}:
        return None
    return Caveat(
        CAVEAT_PACKAGE_LICENCE_ACCOUNT,
        f"the install writes licences for user {HEADLESS_ACCOUNT} (headless_application.cpp:31), and RPCS3 reads "
        "them at launch for the user its own settings make current (gui_application.cpp:297-307), which atlas "
        "does not read — the drive holds other accounts, or which it holds is not established, so the two may "
        "differ",
        {"account": HEADLESS_ACCOUNT, "accounts": tuple(accounts or ())},
    )
