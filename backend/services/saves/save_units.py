"""Save units: the staged zip a save of several files is carried as, packed before it is read and unpacked once written.

Every sync path handles the staged zip as the one file it already handles;
this module is the two hooks that keep the zip and the unit's own files the
same save. Why, and which paths cross each hook, is
``docs/architecture/save-file-sync-architecture.md``'s, "Save units".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.save_answer import stage_unit

if TYPE_CHECKING:
    from domain.save_answer import SaveAnswer, SaveUnit
    from services.protocols import DebugLogger, SaveUnitStore

# The folder under the data root that holds one staging folder per ROM.
SAVE_UNITS_FOLDER = "save-units"


@dataclass(frozen=True)
class SaveUnitsConfig:
    """Frozen wiring bundle handed to ``SaveUnits.__init__``.

    Holds the store that packs and unpacks a unit, the folder the per-ROM
    staging folders are made under (``<data root>/save-units``), and the
    ``DebugLogger`` seam.
    """

    store: SaveUnitStore
    staging_root: str
    log_debug: DebugLogger


class SaveUnits:
    """Stages a save unit's zip, packs it from the unit and unpacks a written one into the unit.

    Remembers the unit behind every zip it packed, so a step that has just
    written that zip — which knows only its path — has it unpacked. A zip is
    always packed in the operation that writes it, since every write path
    reads the save answer first, so the unit remembered is the one that
    operation read. Takes no lock: callers hold the ROM's ``rom_lock`` where
    their path does.
    """

    def __init__(self, *, config: SaveUnitsConfig) -> None:
        self._store = config.store
        self._staging_root = config.staging_root
        self._log_debug = config.log_debug
        self._units_by_zip: dict[str, SaveUnit] = {}

    @property
    def staging_root(self) -> str:
        """The folder every ROM's staging folder is made in."""
        return self._staging_root

    def stage(self, rom_id: int, answer: SaveAnswer, rom_stem: str) -> SaveAnswer:
        """*answer* with its unit's zip named ``<rom_stem>.zip`` in this ROM's staging folder.

        An answer without a unit is returned as it is.
        """
        return stage_unit(
            answer, staging_directory=os.path.join(self._staging_root, str(int(rom_id))), rom_stem=rom_stem
        )

    def pack(self, answer: SaveAnswer) -> None:
        """Rebuild a staged unit's zip from the unit's files; nothing for any other answer.

        Only reads the unit, so it runs whether or not the game is running.
        Raises what the store raises: a zip that could not be rebuilt must not
        be read as the save.
        """
        unit = answer.unit
        directory = answer.sync_directory
        if unit is None or directory is None or len(answer.synced_names) != 1:
            return
        zip_path = os.path.join(directory, answer.synced_names[0])
        self._units_by_zip[zip_path] = unit
        packed = self._store.pack(unit, zip_path)
        self._log_debug(f"save unit {unit.root}: {'packed into' if packed else 'no files, so no'} {zip_path}")

    def unpack_placed(self, zip_path: str) -> None:
        """Unpack the zip just written at *zip_path* into its unit; nothing where it is no unit's zip.

        Then packs the zip again from what was written, so it carries the
        mtime the next pack gives it. Raises what the store raises, with the
        unit as it was: the step that wrote the zip has then failed.
        """
        unit = self._units_by_zip.get(zip_path)
        if unit is None:
            return
        self._store.unpack(zip_path, unit)
        self._store.pack(unit, zip_path)
        self._log_debug(f"save unit {unit.root}: unpacked {zip_path}")

    def clear_placed(self, zip_path: str) -> None:
        """Remove the files of the unit whose zip *zip_path* is; nothing where it is no unit's zip.

        Destructive, and called only once that zip — packed from the unit in
        the same operation — has been moved into ``.romm-backup``, or under the
        confirmation that removing the game's local saves asked for. Raises
        what the store raises.
        """
        unit = self._units_by_zip.get(zip_path)
        if unit is None:
            return
        self._store.clear(unit)
        self._log_debug(f"save unit {unit.root}: cleared after {zip_path}")
