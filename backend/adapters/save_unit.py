"""Filesystem adapter that packs a save unit into its staged zip and unpacks a zip into the unit.

Implements ``services.protocols.SaveUnitStore``. Which files are the unit is
the save answer's (``domain.save_answer.SaveUnit``); this module only reads and
writes them. The rules both directions keep are
``docs/architecture/save-file-sync-architecture.md``'s, "Save units".
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import zipfile
from typing import TYPE_CHECKING

from lib.path_safety import PathTraversalError, safe_join, safe_path_component

if TYPE_CHECKING:
    import logging

    from domain.save_answer import SaveUnit

# The earliest timestamp a zip entry can carry. Every entry gets it, so the
# bytes of a pack depend on the members' names and contents alone.
_ENTRY_DATE_TIME = (1980, 1, 1, 0, 0, 0)

# A regular file, rw-r--r--, in the high 16 bits zipfile keeps Unix modes in.
_ENTRY_EXTERNAL_ATTR = 0o100644 << 16


class SaveUnitAdapter:
    """Synchronous pack and unpack of save units; callers in an async context offload it."""

    def __init__(self, *, logger: logging.Logger) -> None:
        self._logger = logger

    def pack(self, unit: SaveUnit, zip_path: str) -> bool:
        """Write *unit*'s files into *zip_path*, answering whether there was any file to write.

        Entries are sorted by name, named by their path below the root with
        ``/`` separators, and stamped with one fixed timestamp, so the same
        files always give the same bytes. The zip's mtime is the newest
        member's. The zip is written beside *zip_path* and moved over it once
        complete. A unit with no files leaves no zip: a stale one is removed.
        A link is never packed — it could name a file outside the root — and
        is logged instead.
        """
        members = self._members(unit)
        if not members:
            with contextlib.suppress(FileNotFoundError):
                os.remove(zip_path)
            return False
        directory = os.path.dirname(zip_path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".", suffix=".packing")
        try:
            with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w") as archive:
                for name, path in members:
                    info = zipfile.ZipInfo(name, date_time=_ENTRY_DATE_TIME)
                    info.external_attr = _ENTRY_EXTERNAL_ATTR
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with open(path, "rb") as source:
                        archive.writestr(info, source.read())
            newest = max(os.stat(path).st_mtime for _name, path in members)
            os.utime(tmp_path, (newest, newest))
            os.replace(tmp_path, zip_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.remove(tmp_path)
            raise
        return True

    def unpack(self, zip_path: str, unit: SaveUnit) -> None:
        """Replace *unit*'s files with the entries of *zip_path*.

        Every entry name is checked before anything is written, and the
        entries land in a temporary folder beside the root first. A folder
        unit's old root is moved aside, the new one moved in, and the old one
        deleted only once that succeeded; any failure puts the old root back.
        A member-set unit has each entry moved over its file in the root, and
        then the named members the zip does not hold removed; no other file in
        the root is touched. Raises :class:`PathTraversalError` for an entry
        that is no file below the root, and ``ValueError`` for one that would
        replace a file in a member set's root that is not a named member — in
        both cases with nothing written.
        """
        root = os.path.normpath(unit.root)
        with zipfile.ZipFile(zip_path) as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            names = [_entry_name(info.filename, root, unit) for info in entries]
            if unit.members is not None:
                _refuse_foreign_files(names, root, unit.members)
            parent = os.path.dirname(root)
            os.makedirs(parent, exist_ok=True)
            staging = tempfile.mkdtemp(dir=parent, prefix=f".{os.path.basename(root)}.unpacking-")
            try:
                # mkdtemp makes the folder private, and for a folder unit it becomes the root.
                os.chmod(staging, 0o755)
                for info, name in zip(entries, names, strict=True):
                    target = os.path.join(staging, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with archive.open(info) as source, open(target, "wb") as out:
                        shutil.copyfileobj(source, out)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        if unit.members is None:
            self._place_folder(staging, root)
        else:
            self._place_members(staging, root, names, unit.members)

    def clear(self, unit: SaveUnit) -> None:
        """Remove *unit*'s files; files that are already gone are no error.

        A folder unit loses its root and everything below it, and nothing
        beside the root; a root that is a link raises ``OSError`` with nothing
        removed, since removing it would reach whatever it names. A member set
        loses the named members directly in the root, and no other file there.
        """
        root = os.path.normpath(unit.root)
        if unit.members is not None:
            for name in unit.members:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(root, safe_path_component(name)))
            return
        if os.path.islink(root):
            raise OSError(f"the save folder {root} is a link; nothing was removed")
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(root)

    def _members(self, unit: SaveUnit) -> list[tuple[str, str]]:
        """``(entry name, path)`` for every file of *unit* on disk, sorted by entry name."""
        root = os.path.normpath(unit.root)
        if not os.path.isdir(root):
            return []
        found: list[tuple[str, str]] = []
        if unit.members is not None:
            for name in unit.members:
                path = os.path.join(root, safe_path_component(name))
                if os.path.islink(path):
                    self._logger.warning("Save unit: not packing the link %s", path)
                elif os.path.isfile(path):
                    found.append((_archived(name, unit), path))
            return sorted(found)
        for directory, subdirs, files in os.walk(root):
            for subdir in subdirs:
                if os.path.islink(os.path.join(directory, subdir)):
                    self._logger.warning("Save unit: not packing the link %s", os.path.join(directory, subdir))
            for file_name in files:
                path = os.path.join(directory, file_name)
                if os.path.islink(path):
                    self._logger.warning("Save unit: not packing the link %s", path)
                    continue
                if os.path.isfile(path):
                    found.append((_archived(os.path.relpath(path, root).replace(os.sep, "/"), unit), path))
        return sorted(found)

    def _place_folder(self, staging: str, root: str) -> None:
        """Put *staging* where *root* is, keeping the old root until the new one is in place."""
        if os.path.islink(root):
            shutil.rmtree(staging, ignore_errors=True)
            raise OSError(f"the save folder {root} is a link; nothing was replaced")
        previous = f"{staging}.previous"
        had_root = os.path.lexists(root)
        try:
            if had_root:
                os.rename(root, previous)
            try:
                os.rename(staging, root)
            except BaseException:
                if had_root:
                    os.rename(previous, root)
                raise
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        if had_root:
            try:
                shutil.rmtree(previous)
            except OSError as e:
                self._logger.warning("Save unit: could not remove the replaced %s: %s", previous, e)

    def _place_members(self, staging: str, root: str, names: list[str], members: tuple[str, ...]) -> None:
        """Move each extracted entry over its file in *root*, then remove the named *members* the zip lacks."""
        try:
            os.makedirs(root, exist_ok=True)
            for name in names:
                os.replace(os.path.join(staging, name), os.path.join(root, name))
            for name in set(members) - set(names):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(os.path.join(root, safe_path_component(name)))
        finally:
            shutil.rmtree(staging, ignore_errors=True)


def _archived(name: str, unit: SaveUnit) -> str:
    """*name* as the zip carries it: under the unit's archive folder where it has one."""
    return name if unit.archive_folder is None else f"{unit.archive_folder}/{name}"


def _entry_name(entry: str, root: str, unit: SaveUnit) -> str:
    """The name below *root* that *entry* writes, when it is a file the unit may hold.

    Raises :class:`PathTraversalError` otherwise, including for an entry that
    is not under the unit's archive folder: a zip laid out another way would
    land its files somewhere the emulator does not read.
    """
    name = entry
    if unit.archive_folder is not None:
        prefix = f"{unit.archive_folder}/"
        if not entry.startswith(prefix):
            raise PathTraversalError(f"zip entry is not under {prefix!r}: {entry!r}")
        name = entry[len(prefix) :]
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise PathTraversalError(f"zip entry is no relative file name: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathTraversalError(f"zip entry is no relative file name: {name!r}")
    if unit.members is not None:
        safe_path_component(name)
    safe_join(root, *parts)
    return name


def _refuse_foreign_files(names: list[str], root: str, members: tuple[str, ...]) -> None:
    """Raise where an entry would replace a file in *root* that is not one of *members*."""
    named = set(members)
    for name in names:
        if name not in named and os.path.lexists(os.path.join(root, name)):
            raise ValueError(f"zip entry {name!r} would replace a file in {root} that is not this game's")
