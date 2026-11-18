"""What a download whose content is a package becomes: a game installed into its emulator (ADR-0051).

The resolver states whether a recorded download is such a package and how it
installs (``PackageInstallReader``). Where it is, the install runs to its end,
and the game counts as installed exactly where every boot file the resolver
names stands afterwards — never by the command's exit status. An install that
succeeded moves the install record onto the installed title and removes the
download; one that did not leaves the download recorded as it was, and says
why.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from domain.package_install import (
    DID_NOT_FINISH,
    NO_BOOT_FILE,
    NOT_STARTED,
    InstalledTitle,
    PackageInstallRefused,
    package_folder,
)
from domain.retrodeck_folders import FolderRefused, folder_of
from lib.path_safety import is_inside_folder

if TYPE_CHECKING:
    import logging

    from domain.package_install import PackageInstallPlan
    from domain.rom_install import RomInstall
    from services.downloads.queue import DownloadQueue
    from services.protocols import (
        DownloadFileStore,
        PackageInstallControl,
        PackageInstallReader,
        RetroDeckFolders,
        UnitOfWorkFactory,
    )


@dataclass(frozen=True, slots=True)
class PackageInstalled:
    """A package install that installed the game: the record now names *file_path*, the title's boot file."""

    file_path: str


@dataclass(frozen=True, slots=True)
class PackageNotInstalled:
    """A package install that was refused or did not install the game; the download stays recorded as it was.

    ``reason`` is one of :mod:`domain.package_install`'s words, and
    ``installer`` the emulator that was to install it, where one was named.
    """

    reason: str
    installer: str | None


@dataclass(frozen=True)
class DownloadPackageInstallConfig:
    """Frozen wiring bundle handed to ``DownloadPackageInstall.__init__``.

    ``package_installs`` states the install, ``install_control`` runs it, for
    at most ``timeout_seconds``; ``download_file_store`` checks its boot file
    and removes the download, which only inside its system's own ROM folder
    (``retrodeck_folders``) is removed. ``queue`` reports the installing state.
    """

    package_installs: PackageInstallReader
    install_control: PackageInstallControl
    download_file_store: DownloadFileStore
    retrodeck_folders: RetroDeckFolders
    uow_factory: UnitOfWorkFactory
    queue: DownloadQueue
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    timeout_seconds: float


class DownloadPackageInstall:
    """Installs a recorded download whose content is a package into its emulator."""

    def __init__(self, *, config: DownloadPackageInstallConfig) -> None:
        self._package_installs = config.package_installs
        self._install_control = config.install_control
        self._download_file_store = config.download_file_store
        self._retrodeck_folders = config.retrodeck_folders
        self._uow_factory = config.uow_factory
        self._queue = config.queue
        self._loop = config.loop
        self._logger = config.logger
        self._timeout_seconds = config.timeout_seconds

    async def install(
        self, rom_id: int, rom_name: str, platform_name: str, file_name: str
    ) -> PackageInstalled | PackageNotInstalled | None:
        """Install *rom_id*'s recorded download into its emulator where it is a package; ``None`` where it is not.

        The download's folder is what is installed — every package and
        licence in it in one run — or its one file where it has no folder.
        A cancel ends the running install and is re-raised; the download then
        stays recorded as it was.
        """
        install = await self._loop.run_in_executor(None, self._read_io, rom_id)
        if install is None or install.package_boot_file is not None:
            return None
        content = install.file_path
        if install.rom_dir is not None:
            files = await self._loop.run_in_executor(
                None, self._download_file_store.scan_files_with_sizes, install.rom_dir
            )
            content = package_folder([path for path, _size in files], install.rom_dir)
        writable = (install.rom_dir or os.path.dirname(install.file_path),)
        plan = await self._loop.run_in_executor(
            None, partial(self._package_installs.package_install, install.system, content, writable=writable)
        )
        if plan is None:
            return None
        if isinstance(plan, PackageInstallRefused):
            self._logger.warning(f"Package install of {rom_name} not run: {plan.reason}")
            return PackageNotInstalled(plan.reason, plan.installer)
        self._queue.report_installing(rom_id, rom_name, platform_name, file_name)
        failure = await self._run(plan, rom_name)
        if failure is not None:
            return PackageNotInstalled(failure, plan.installer)
        recorded = await self._loop.run_in_executor(None, self._record_io, rom_id, install, plan.title)
        if not recorded:
            return PackageNotInstalled(NO_BOOT_FILE, plan.installer)
        return PackageInstalled(plan.title.boot_file)

    async def _run(self, plan: PackageInstallPlan, rom_name: str) -> str | None:
        """Run *plan*'s command to its end; answer why it installed nothing, or ``None`` where its boot file stands."""
        self._logger.info(f"Package install of {rom_name} starting: {plan.title.folder}")
        try:
            async with asyncio.timeout(self._timeout_seconds):
                status = await self._install_control.run(plan.argv)
        except TimeoutError:
            self._logger.error(f"Package install of {rom_name} did not end within {self._timeout_seconds:.0f}s")
            return DID_NOT_FINISH
        except OSError as exc:
            self._logger.error(f"Package install of {rom_name} could not be started: {exc}")
            return NOT_STARTED
        if not await self._loop.run_in_executor(None, self._download_file_store.exists, plan.title.boot_file):
            self._logger.error(f"Package install of {rom_name} ended ({status}) with no {plan.title.boot_file}")
            return NO_BOOT_FILE
        self._logger.info(f"Package install of {rom_name} ended ({status}): {plan.title.boot_file}")
        return None

    def _read_io(self, rom_id: int) -> RomInstall | None:
        with self._uow_factory() as uow:
            return uow.rom_installs.get(rom_id)

    def _record_io(self, rom_id: int, downloaded: RomInstall, title: InstalledTitle) -> bool:
        """Move *rom_id*'s record onto *title*, then remove the download it named; ``False`` where the record moved on.

        The record is moved only while it still names the download that was
        installed. The download goes once the record no longer names it; a
        removal that fails leaves it where it lies and is logged, since the
        game is installed either way.
        """
        with self._uow_factory() as uow:
            install = uow.rom_installs.get(rom_id)
            if install is None or (install.file_path, install.rom_dir) != (downloaded.file_path, downloaded.rom_dir):
                return False
            install.install_from_package(title)
            uow.rom_installs.save(install)
        self._remove_download(downloaded)
        return True

    def _remove_download(self, downloaded: RomInstall) -> None:
        path = downloaded.rom_dir or downloaded.file_path
        folder = folder_of(self._retrodeck_folders.rom_folders([downloaded.system]), downloaded.system)
        if isinstance(folder, FolderRefused) or not is_inside_folder(path, folder) or path == folder:
            self._logger.warning(f"Kept the installed package's download {path}: it is not inside a ROM folder")
            return
        try:
            if downloaded.rom_dir is not None:
                self._download_file_store.remove_tree(path)
            else:
                self._download_file_store.remove_file(path)
        except OSError as exc:
            self._logger.warning(f"Could not remove the installed package's download {path}: {exc}")
