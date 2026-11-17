"""ExtraContentOffer — what a game's extra content is, whether it is offered, and which of it is on this device.

Extra content is offered only where the resolver states the emulator entry the
game starts with loads it from folders (``ExtraContentReader``); everywhere
else the answer offers nothing and lists nothing, without asking RomM. Where it
is offered, the answer lists every update and DLC file RomM holds for the
game, which of them a download ticks before the user answers, which are
recorded on the install and still lie in the game's folder, and what stands in
the way of the emulator loading them: the game's folder outside every folder
it scans, or scanned only beside the launch, and a file whose extension it
does not read from a folder. Which of it is fetched, and how, is the
transfer's.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.emulator_sources import RETRODECK
from domain.extra_content import extra_content_files, read_from_folders, ticked_by_default
from domain.retrodeck_folders import FolderRefused
from lib.errors import Refused
from lib.path_safety import PathTraversalError, safe_join
from services.downloads._names import safe_extract_dir_name

if TYPE_CHECKING:
    import asyncio
    import logging

    from domain.extra_content import ExtraContentFile, ExtraContentFolders
    from domain.rom_install import RomInstall
    from services.protocols import (
        ActiveCoreReader,
        DownloadFileStore,
        ExtraContentReader,
        PlatformSystems,
        RetroDeckFolders,
        RommRomReader,
        UnitOfWorkFactory,
    )


@dataclass(frozen=True)
class ExtraContentOfferConfig:
    """Frozen wiring bundle handed to ``ExtraContentOffer.__init__``.

    ``active_core`` names the entry the game starts with, which the resolver
    is asked about through ``extra_content``.
    """

    uow_factory: UnitOfWorkFactory
    romm_api: RommRomReader
    platform_systems: PlatformSystems
    retrodeck_folders: RetroDeckFolders
    extra_content: ExtraContentReader
    active_core: ActiveCoreReader
    download_file_store: DownloadFileStore
    loop: asyncio.AbstractEventLoop
    logger: logging.Logger


class ExtraContentOffer:
    """Answers the game page's question about a game's extra content. Reads only."""

    def __init__(self, *, config: ExtraContentOfferConfig) -> None:
        self._uow_factory = config.uow_factory
        self._romm_api = config.romm_api
        self._platform_systems = config.platform_systems
        self._retrodeck_folders = config.retrodeck_folders
        self._extra_content = config.extra_content
        self._active_core = config.active_core
        self._download_file_store = config.download_file_store
        self._loop = config.loop
        self._logger = config.logger

    async def get_extra_content(self, rom_id: int | str) -> dict[str, Any]:
        """The game's extra content as the game page and a download's question show it.

        Answers ``{success, offered, installed, files, game_folder_scanned,
        rom_folder}``; where nothing is offered, ``files``
        is empty and RomM is not asked. Each file is ``{file_id, file_name,
        rel_path, category, size_bytes, on_device, ticked, read_from_folders}``.
        Refuses ``not_found`` for a game Tender does not know; a RomM error is
        raised, as a ROM read's is.
        """
        return await self._loop.run_in_executor(None, self._answer_io, int(rom_id))

    def _answer_io(self, rom_id: int) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
        if rom is None:
            raise Refused("not_found", f"ROM {rom_id} is not in the library")
        system = install.system if install is not None else self._platform_system(rom.platform_slug)
        if system is None:
            return _not_offered(installed=install is not None)
        label = self._label(rom_id)
        folders = self._extra_content.extra_content_folders(
            system, label=label, content_path=install.rom_dir if install is not None else None
        )
        if not folders.offered:
            return _not_offered(installed=install is not None)
        rom_detail = self._romm_api.get_rom(rom_id)
        rom_folder = self._rom_folder(system)
        if install is None and rom_folder is not None:
            game_folder = os.path.join(rom_folder, safe_extract_dir_name(rom_detail, self._logger))
            folders = self._extra_content.extra_content_folders(system, label=label, content_path=game_folder)
        files = extra_content_files(rom_detail)
        ticked = ticked_by_default(files)
        on_device = self._on_device(install)
        return {
            "success": True,
            "offered": True,
            "installed": install is not None,
            "files": [_file_row(entry, entry.file_id in ticked, on_device, folders) for entry in files],
            "game_folder_scanned": folders.game_folder_scanned,
            "rom_folder": rom_folder,
        }

    def _platform_system(self, platform_slug: str) -> str | None:
        return self._platform_systems.platform_system(platform_slug, source=RETRODECK).taken

    def _label(self, rom_id: int) -> str | None:
        resolved = self._active_core.resolve_rom(rom_id)
        option = resolved.choice.option if resolved is not None else None
        return option.label if option is not None else None

    def _rom_folder(self, system: str) -> str | None:
        folder = self._retrodeck_folders.download_folder(system)
        return None if isinstance(folder, FolderRefused) else folder

    def _on_device(self, install: RomInstall | None) -> frozenset[int]:
        """The recorded files of extra content that still lie at their place in the game's folder."""
        if install is None or install.rom_dir is None:
            return frozenset()
        found: set[int] = set()
        for entry in install.extra_content:
            try:
                path = safe_join(install.rom_dir, entry.rel_path)
            except PathTraversalError:
                continue
            if self._download_file_store.exists(path):
                found.add(entry.file_id)
        return frozenset(found)


def _not_offered(*, installed: bool) -> dict[str, Any]:
    return {
        "success": True,
        "offered": False,
        "installed": installed,
        "files": [],
        "game_folder_scanned": None,
        "rom_folder": None,
    }


def _file_row(
    entry: ExtraContentFile, ticked: bool, on_device: frozenset[int], folders: ExtraContentFolders
) -> dict[str, Any]:
    return {
        "file_id": entry.file_id,
        "file_name": entry.file_name,
        "rel_path": entry.rel_path,
        "category": entry.category,
        "size_bytes": entry.size_bytes,
        "on_device": entry.file_id in on_device,
        "ticked": ticked,
        "read_from_folders": read_from_folders(entry, folders.extensions),
    }
