"""Atlas package-install adapter — the one place the resolver's package-install answer is read.

The resolver states how a package, or a folder of them, is installed into the
entry's emulator: the command, every package it takes and where each goes,
and the boot file a game's folder holds once its game is installed. This
module reads that answer into Tender's view (:mod:`domain.package_install`):
the install to run and the game it leaves, why a download whose content is a
package is not installed, or ``None`` where the download is no package to
install. Nothing else in Tender reads the answer.

The command is run as a start's is (:func:`adapters.atlas_launch.read_start`),
so it is complete or refused by the same rules. Whether it succeeded is never
its exit status: RPCS3's states nothing (``exit_status_reports_outcome``), and
the boot file standing afterwards is the sign the resolver names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from _vendor.atlas import (
    CAVEAT_PACKAGE_DRIVE_UNRESOLVED,
    CAVEAT_PACKAGE_HEADER_UNREAD,
    CAVEAT_PACKAGE_INSTALL_PATH_UNREAD,
    CAVEAT_PACKAGE_INSTALL_TAKES_NOTHING,
    CAVEAT_PACKAGE_INSTALL_UNSTATED,
    CAVEAT_PACKAGE_LICENCE_ACCOUNT,
    PACKAGE_DESTINATION_GAME_FOLDER,
    PACKAGE_DESTINATION_UNREAD,
)

from adapters.atlas_launch import read_start
from domain.package_install import (
    COMMAND_INCOMPLETE,
    PackageGameTarget,
    PackageInstallPlan,
    PackageInstallRefused,
    installed_title,
)
from domain.start_command import StartRefused

if TYPE_CHECKING:
    from collections.abc import Callable

    from adapters.emulator_sources import EmulatorSourcesAdapter

# What the answer says about the install, logged and deciding nothing: that no
# command is stated for the entry, that nothing at the path is a package or what
# lies there is not established (each beside no target, which is what decides),
# one package's destination unread or the drive not established (each leaving a
# target Tender reads as unplaced), and the licence written for an account the
# emulator may not start as.
_LOGGED = frozenset(
    {
        CAVEAT_PACKAGE_INSTALL_UNSTATED,
        CAVEAT_PACKAGE_INSTALL_TAKES_NOTHING,
        CAVEAT_PACKAGE_INSTALL_PATH_UNREAD,
        CAVEAT_PACKAGE_HEADER_UNREAD,
        CAVEAT_PACKAGE_DRIVE_UNRESOLVED,
        CAVEAT_PACKAGE_LICENCE_ACCOUNT,
    }
)


def _game_target(target: Any) -> PackageGameTarget:
    folder = target.install_folder
    boot = target.boot_file
    return PackageGameTarget(
        folder=folder.host_path if folder is not None else None,
        boot_file=boot.host_path if boot is not None else None,
        boot_file_in_emulator=boot.frontend_path if boot is not None else None,
    )


def read_package_install(
    answer: Any, *, writable: tuple[str, ...] = ()
) -> PackageInstallPlan | PackageInstallRefused | None:
    """*answer* in Tender's words, the folders in *writable* granted to a Flatpak install.

    ``None`` where the answer establishes no game to install: no command
    beside a statement that nothing there is a package, or a command whose
    packages install no game. A command refused for any other reason is
    ``None`` as well — with no command the answer lists no package, so
    nothing says the download was one. A package whose destination was not
    read, beside no game, refuses; so does a command Tender cannot run as
    stated, and a set of packages that is not exactly one game.
    """
    entry = answer.entry
    installer = entry.emulator if entry is not None else None
    if answer.command is None:
        return None
    games = tuple(_game_target(t) for t in answer.package_targets if t.destination == PACKAGE_DESTINATION_GAME_FOLDER)
    if not games:
        unread = any(t.destination == PACKAGE_DESTINATION_UNREAD for t in answer.package_targets)
        return PackageInstallRefused(COMMAND_INCOMPLETE, installer) if unread else None
    title = installed_title(games)
    if isinstance(title, PackageInstallRefused):
        return PackageInstallRefused(title.reason, installer)
    start = read_start(answer, writable=writable)
    if title is None or isinstance(start, StartRefused):
        return PackageInstallRefused(COMMAND_INCOMPLETE, installer)
    return PackageInstallPlan(argv=start.argv, title=title, installer=installer)


class AtlasPackageInstallAdapter:
    """Asks a game's answering emulator source how its downloaded content installs, and reads it into Tender's view.

    Keeps no answer of its own: each is asked through a fresh reading of the
    emulator sources, because what lies in a download's folder is the
    question.
    """

    def __init__(self, *, sources: EmulatorSourcesAdapter, log_debug: Callable[[str], None]) -> None:
        self._sources = sources
        self._log_debug = log_debug

    def package_install(
        self, system: str, content_path: str, *, writable: tuple[str, ...] = ()
    ) -> PackageInstallPlan | PackageInstallRefused | None:
        """How *content_path*, *system*'s downloaded content, installs into its emulator — :func:`read_package_install`.

        ``None`` too where no source answers for *system* or the resolver
        could not be asked.
        """
        reading = self._sources.read()
        installation = reading.answering_installation(system)
        if installation is None:
            self._log_debug(f"[package] no emulator source answers ({reading.no_answer_reason()})")
            return None
        try:
            answer = installation.package_install_command(system, content_path)
        except Exception as exc:
            self._log_debug(f"[package] resolver failed on package_install_command({system!r}): {exc!r}")
            return None
        codes = sorted({caveat.code for caveat in answer.caveats})
        said = sorted(set(codes) & _LOGGED)
        self._log_debug(
            f"[package] {system}: command={answer.command is not None} "
            f"targets={len(answer.package_targets)} caveats={codes} noted={said}"
        )
        return read_package_install(answer, writable=writable)
