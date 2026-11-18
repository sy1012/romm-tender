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
        the root is touched. A unit of prefixed folders has its member folders
        moved aside, the zip's folders moved in, and the aside ones deleted
        only once that succeeded; any failure puts them back, and no other
        folder in the root is touched. A unit of archive roots has each folder
        whose root name the zip carries files under replaced whole, as a
        folder unit's root is, and every other one left as it is; the folders
        moved aside are deleted only once every one is replaced, and any
        failure puts them all back. Raises :class:`PathTraversalError` for an
        entry that is no file below the root (or, for prefixed folders, no
        file inside a folder named with the prefix; for archive roots, no
        file inside a folder named as one of its roots), ``ValueError`` for
        one that would replace a file or folder in the root that is not a
        named member, and ``OSError`` for an archive root to replace that is
        a link or no folder — in every case with nothing written.
        """
        if unit.archive_roots is not None:
            self._unpack_rooted(zip_path, unit.archive_roots)
            return
        if unit.prefix is not None:
            self._unpack_prefixed(zip_path, unit)
            return
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
        A unit of prefixed folders loses its member folders and nothing else in
        the root; a member that is a link or no folder raises ``OSError`` with
        nothing removed. A unit of archive roots loses each of its folders and
        everything below them, and nothing beside them; one that is a link or
        no folder raises ``OSError`` with nothing removed.
        """
        if unit.archive_roots is not None:
            for path in _root_folders(unit.archive_roots, [name for name, _folder in unit.archive_roots]):
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(path)
            return
        root = os.path.normpath(unit.root)
        if unit.prefix is not None:
            for path in _member_folders(root, unit):
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(path)
            return
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
        if unit.archive_roots is not None:
            found_below: list[tuple[str, str]] = []
            for root_name, folder in unit.archive_roots:
                if os.path.isdir(folder):
                    found_below.extend((f"{root_name}/{name}", path) for name, path in self._walk(folder))
            return sorted(found_below)
        root = os.path.normpath(unit.root)
        if not os.path.isdir(root):
            return []
        found: list[tuple[str, str]] = []
        if unit.prefix is not None:
            for folder in unit.members or ():
                path = os.path.join(root, safe_path_component(folder))
                if os.path.islink(path):
                    self._logger.warning("Save unit: not packing the link %s", path)
                elif os.path.isdir(path):
                    found.extend((f"{folder}/{name}", file_path) for name, file_path in self._walk(path))
            return sorted(found)
        if unit.members is not None:
            for name in unit.members:
                path = os.path.join(root, safe_path_component(name))
                if os.path.islink(path):
                    self._logger.warning("Save unit: not packing the link %s", path)
                elif os.path.isfile(path):
                    found.append((_archived(name, unit), path))
            return sorted(found)
        return sorted((_archived(name, unit), path) for name, path in self._walk(root))

    def _walk(self, top: str) -> list[tuple[str, str]]:
        """``(name below top with / separators, path)`` for every regular file below *top*; links are logged."""
        found: list[tuple[str, str]] = []
        for directory, subdirs, files in os.walk(top):
            for subdir in subdirs:
                if os.path.islink(os.path.join(directory, subdir)):
                    self._logger.warning("Save unit: not packing the link %s", os.path.join(directory, subdir))
            for file_name in files:
                path = os.path.join(directory, file_name)
                if os.path.islink(path):
                    self._logger.warning("Save unit: not packing the link %s", path)
                    continue
                if os.path.isfile(path):
                    found.append((os.path.relpath(path, top).replace(os.sep, "/"), path))
        return found

    def _unpack_prefixed(self, zip_path: str, unit: SaveUnit) -> None:
        """Replace a unit of prefixed folders with the folders *zip_path* holds at its top."""
        root = os.path.normpath(unit.root)
        with zipfile.ZipFile(zip_path) as archive:
            entries = [info for info in archive.infolist() if not info.is_dir()]
            names = [_prefixed_entry_name(info.filename, root, unit) for info in entries]
            incoming = sorted({name.split("/", 1)[0] for name in names})
            replaced = [os.path.basename(path) for path in _member_folders(root, unit) if os.path.lexists(path)]
            _refuse_foreign_folders(incoming, root, unit)
            os.makedirs(root, exist_ok=True)
            # Beside the root's real place, not its link's: RetroDECK links
            # PPSSPP's SAVEDATA into its saves folder, which may be on the SD
            # card (emu-atlas's recorded machine ppsspp-savedata.json), and a
            # rename into the root works only from the same filesystem.
            beside = os.path.dirname(os.path.realpath(root))
            staging = tempfile.mkdtemp(dir=beside, prefix=f".{os.path.basename(root)}.unpacking-")
            try:
                for info, name in zip(entries, names, strict=True):
                    target = os.path.join(staging, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with archive.open(info) as source, open(target, "wb") as out:
                        shutil.copyfileobj(source, out)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        self._swap_folders(staging, root, beside, replaced, incoming)

    def _unpack_rooted(self, zip_path: str, roots: tuple[tuple[str, str], ...]) -> None:
        """Replace each of *roots*' folders that *zip_path* carries files under with what it carries."""
        folders = {name: os.path.normpath(folder) for name, folder in roots}
        with zipfile.ZipFile(zip_path) as archive:
            entries: list[tuple[zipfile.ZipInfo, str, list[str]]] = []
            for info in archive.infolist():
                root_name, below = _rooted_entry_parts(info.filename, folders, is_dir=info.is_dir())
                if not info.is_dir():
                    entries.append((info, root_name, below))
            incoming = sorted({root_name for _info, root_name, _below in entries})
            targets = dict(zip(incoming, _root_folders(roots, incoming), strict=True))
            stagings: dict[str, str] = {}
            try:
                for root_name in incoming:
                    folder = targets[root_name]
                    parent = os.path.dirname(folder)
                    os.makedirs(parent, exist_ok=True)
                    # Beside the folder's real place, not its link's: RetroDECK
                    # may link Azahar's sdmc, or a folder in it, onto the SD
                    # card, and a rename into the folder works only from the
                    # same filesystem.
                    staging = tempfile.mkdtemp(
                        dir=os.path.realpath(parent), prefix=f".{os.path.basename(folder)}.unpacking-"
                    )
                    stagings[root_name] = staging
                    # mkdtemp makes the folder private, and it becomes the root's folder.
                    os.chmod(staging, 0o755)
                for info, root_name, below in entries:
                    target = os.path.join(stagings[root_name], *below)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with archive.open(info) as source, open(target, "wb") as out:
                        shutil.copyfileobj(source, out)
            except BaseException:
                for staging in stagings.values():
                    shutil.rmtree(staging, ignore_errors=True)
                raise
        self._replace_folders([(stagings[name], targets[name]) for name in incoming])

    def _replace_folders(self, moves: list[tuple[str, str]]) -> None:
        """Move each ``(staging, folder)`` pair's staging folder over its folder, as one change.

        The folders replaced are moved beside their staging folders first and
        deleted only once every staging folder is in place; a failure moves
        everything back. Where moving them back fails too, what could not be
        moved is left where it lies and the place is logged.
        """
        moved_out: list[tuple[str, str]] = []
        moved_in: list[tuple[str, str]] = []
        try:
            for staging, folder in moves:
                if os.path.lexists(folder):
                    os.rename(folder, f"{staging}.previous")
                    moved_out.append((folder, f"{staging}.previous"))
                os.rename(staging, folder)
                moved_in.append((staging, folder))
        except BaseException:
            try:
                for staging, folder in reversed(moved_in):
                    os.rename(folder, staging)
                for folder, aside in reversed(moved_out):
                    os.rename(aside, folder)
            except OSError as e:
                self._logger.error("Save unit: could not put back the folders %s: %s", moved_out, e)
            for staging, _folder in moves:
                shutil.rmtree(staging, ignore_errors=True)
            raise
        for _folder, aside in moved_out:
            try:
                shutil.rmtree(aside)
            except OSError as e:
                self._logger.warning("Save unit: could not remove the replaced %s: %s", aside, e)

    def _swap_folders(self, staging: str, root: str, beside: str, replaced: list[str], incoming: list[str]) -> None:
        """Move *replaced* out of *root* into a folder in *beside*, and *incoming* in from *staging*.

        The folders moved out are deleted only once every one moved in; a
        failure moves everything back. Where moving them back fails too, they
        are left where they were moved to and the place is logged.
        """
        aside = tempfile.mkdtemp(dir=beside, prefix=f".{os.path.basename(root)}.previous-")
        moved_out: list[str] = []
        moved_in: list[str] = []
        try:
            for name in replaced:
                os.rename(os.path.join(root, name), os.path.join(aside, name))
                moved_out.append(name)
            for name in incoming:
                os.rename(os.path.join(staging, name), os.path.join(root, name))
                moved_in.append(name)
        except BaseException:
            try:
                for name in reversed(moved_in):
                    os.rename(os.path.join(root, name), os.path.join(staging, name))
                for name in reversed(moved_out):
                    os.rename(os.path.join(aside, name), os.path.join(root, name))
                os.rmdir(aside)
            except OSError as e:
                self._logger.error("Save unit: could not put back the folders of %s, kept in %s: %s", root, aside, e)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        shutil.rmtree(staging, ignore_errors=True)
        try:
            shutil.rmtree(aside)
        except OSError as e:
            self._logger.warning("Save unit: could not remove the replaced %s: %s", aside, e)

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
    parts = _relative_parts(name)
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


def _relative_parts(name: str) -> list[str]:
    """*name*'s ``/``-separated parts; raises :class:`PathTraversalError` where it is no relative file name."""
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise PathTraversalError(f"zip entry is no relative file name: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathTraversalError(f"zip entry is no relative file name: {name!r}")
    return parts


def _prefixed_entry_name(entry: str, root: str, unit: SaveUnit) -> str:
    """*entry*, when it is a file inside a folder at the zip's top whose name starts with the unit's prefix.

    Raises :class:`PathTraversalError` otherwise — a file at the zip's top
    included: the save is the folders, and a file beside them would land in
    the root other games' folders share.
    """
    parts = _relative_parts(entry)
    folder = parts[0]
    if len(parts) < 2:
        raise PathTraversalError(f"zip entry is not inside a save folder: {entry!r}")
    if not unit.prefix_matches(folder):
        raise PathTraversalError(f"zip entry's folder does not start with {unit.prefix!r}: {entry!r}")
    safe_join(root, safe_path_component(folder), *parts[1:])
    return entry


def _member_folders(root: str, unit: SaveUnit) -> list[str]:
    """The paths of *unit*'s member folders in *root*; raises ``OSError`` where one is a link or no folder."""
    paths: list[str] = []
    for name in unit.members or ():
        path = os.path.join(root, safe_path_component(name))
        if os.path.islink(path):
            raise OSError(f"the save folder {path} is a link; nothing was changed")
        if os.path.lexists(path) and not os.path.isdir(path):
            raise OSError(f"the save folder {path} is no folder; nothing was changed")
        paths.append(path)
    return paths


def _refuse_foreign_folders(incoming: list[str], root: str, unit: SaveUnit) -> None:
    """Raise where a folder the zip brings would replace one in *root* that is not one of *unit*'s members.

    A folder named with the prefix that the answer does not name as a member
    — a game's installed data beside its saves — is not in the zip the unit
    was packed into, so replacing it would lose it.
    """
    named = set(unit.members or ())
    for name in incoming:
        if name not in named and os.path.lexists(os.path.join(root, name)):
            raise ValueError(f"zip folder {name!r} would replace a folder in {root} that is not this game's save")


def _rooted_entry_parts(entry: str, folders: dict[str, str], *, is_dir: bool) -> tuple[str, list[str]]:
    """The archive root *entry* sits under and its parts below that root's folder in *folders*.

    Raises :class:`PathTraversalError` for an entry under no root, a file at
    the zip's top, and any part ``safe_join`` would not keep inside the
    root's folder. A folder entry is checked the same way and may name the
    root alone.
    """
    parts = _relative_parts(entry.removesuffix("/") if is_dir else entry)
    root_name = parts[0]
    if root_name not in folders:
        raise PathTraversalError(f"zip entry is not under one of {sorted(folders)!r}: {entry!r}")
    if len(parts) < 2 and not is_dir:
        raise PathTraversalError(f"zip entry is not inside a save folder: {entry!r}")
    if len(parts) > 1:
        safe_join(folders[root_name], *parts[1:])
    return root_name, parts[1:]


def _root_folders(roots: tuple[tuple[str, str], ...], names: list[str]) -> list[str]:
    """The folders of *roots* named in *names*; raises ``OSError`` where one is a link or no folder."""
    folders = dict(roots)
    paths: list[str] = []
    for name in names:
        path = os.path.normpath(folders[name])
        if os.path.islink(path):
            raise OSError(f"the save folder {path} is a link; nothing was changed")
        if os.path.lexists(path) and not os.path.isdir(path):
            raise OSError(f"the save folder {path} is no folder; nothing was changed")
        paths.append(path)
    return paths
