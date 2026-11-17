"""A game's extra content — the update and DLC files RomM holds beside it — and which of them a download offers.

RomM files a Switch game's updates and add-ons under the ``update`` and ``dlc``
categories (``domain/game_files.py``), and a download of the game leaves them on
the server. Extra content is those files, for a game RomM holds as a folder: a
game RomM holds as one file has no folder to keep any beside it. A file of
extra content goes to the place RomM keeps it at inside the game's folder.

What is ticked when a download asks which to bring is the newest update and
every DLC file. Which update is newest is decided by the rule
docs/architecture/backend-architecture.md, "Extra content", states.

Pure: RomM's payload arrives as a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.game_files import game_files
from domain.iso_time import parse_iso_to_epoch
from domain.refusal import NamedDomainRefused
from domain.rom_files import lands_as_folder

if TYPE_CHECKING:
    from collections.abc import Iterable

UPDATE = "update"
DLC = "dlc"
EXTRA_CONTENT_CATEGORIES: tuple[str, ...] = (UPDATE, DLC)

# The version tag the Switch dumping tools put in a package's file name, such
# as ``Game [0100000000010800][v131072].nsp``: the title version, which counts up.
_VERSION_TAG = re.compile(r"\[v(\d+)\]", re.IGNORECASE)


class UnknownExtraContent(NamedDomainRefused):
    """A file asked for is none of the game's extra content on RomM; ``file_ids`` names those."""

    reason = "unknown_extra_content"


@dataclass(frozen=True, slots=True)
class ExtraContentFile:
    """One update or DLC file of a game on RomM.

    *rel_path* is where RomM keeps it inside the game's folder, and where it
    lands inside the game's folder on this device. *version* is the version tag
    its file name carries, ``None`` where it carries none; *modified* is RomM's
    modification time of the file, ``None`` where the payload states none.
    """

    file_id: int
    file_name: str
    rel_path: str
    size_bytes: int
    category: str
    version: int | None
    modified: str | None


def extra_content_files(rom_detail: dict[str, Any]) -> tuple[ExtraContentFile, ...]:
    """The extra content RomM holds for *rom_detail*, in RomM's order.

    Only a file that can be fetched on its own and placed is listed: one with an
    id, and with a place inside the game's folder. A game RomM holds as one
    file has none.
    """
    if not lands_as_folder(rom_detail):
        return ()
    raw_by_id = {entry.get("id"): entry for entry in rom_detail.get("files") or []}
    files = game_files(rom_detail)
    found: list[ExtraContentFile] = []
    for entry in (*files.fetched, *files.left_out):
        if entry.category not in EXTRA_CONTENT_CATEGORIES or entry.file_id is None or not entry.rel_path:
            continue
        found.append(
            ExtraContentFile(
                file_id=entry.file_id,
                file_name=entry.file_name,
                rel_path=entry.rel_path,
                size_bytes=entry.size_bytes,
                category=str(entry.category),
                version=_version_tag(entry.file_name),
                modified=_modified(raw_by_id.get(entry.file_id) or {}),
            )
        )
    return tuple(found)


def newest_update(files: Iterable[ExtraContentFile]) -> ExtraContentFile | None:
    """The newest of the updates in *files*, or ``None`` where it cannot be told or there is none.

    Where any update's file name carries a version tag, the highest tag wins.
    Else, where any states a modification time, the latest of those wins. Else
    a single update is the newest, and of several none is.
    """
    updates = [entry for entry in files if entry.category == UPDATE]
    tagged = [entry for entry in updates if entry.version is not None]
    if tagged:
        return max(tagged, key=lambda entry: entry.version or 0)
    dated = [(stamp, entry) for entry in updates if (stamp := parse_iso_to_epoch(entry.modified)) is not None]
    if dated:
        return max(dated, key=lambda pair: pair[0])[1]
    return updates[0] if len(updates) == 1 else None


def ticked_by_default(files: tuple[ExtraContentFile, ...]) -> frozenset[int]:
    """The ids a download's question ticks before the user answers: the newest update and every DLC file."""
    newest = newest_update(files)
    ticked = {entry.file_id for entry in files if entry.category == DLC}
    if newest is not None:
        ticked.add(newest.file_id)
    return frozenset(ticked)


def chosen_extra_content(rom_detail: dict[str, Any], file_ids: Iterable[int]) -> tuple[ExtraContentFile, ...]:
    """The extra content *file_ids* name, in RomM's order; raises :class:`UnknownExtraContent` for an id it is not."""
    wanted = {int(file_id) for file_id in file_ids}
    files = extra_content_files(rom_detail)
    unknown = wanted - {entry.file_id for entry in files}
    if unknown:
        raise UnknownExtraContent(
            "RomM holds no update or DLC file of this game with that id", file_ids=sorted(unknown)
        )
    return tuple(entry for entry in files if entry.file_id in wanted)


def read_from_folders(file: ExtraContentFile, extensions: tuple[str, ...]) -> bool | None:
    """Whether the emulator reads *file* from a folder, by the *extensions* it reads; ``None`` where none are known."""
    if not extensions:
        return None
    lowered = file.file_name.lower()
    return any(lowered.endswith(extension.lower()) for extension in extensions)


def _version_tag(file_name: str) -> int | None:
    match = _VERSION_TAG.search(file_name)
    return int(match.group(1)) if match else None


def _modified(entry: dict[str, Any]) -> str | None:
    stamp = entry.get("last_modified") or entry.get("updated_at")
    return stamp if isinstance(stamp, str) and stamp else None


@dataclass(frozen=True, slots=True)
class ExtraContentFolders:
    """Tender's reading of whether a game's emulator loads extra content lying in folders, and where.

    *offered* is ``True`` only where the resolver states the emulator entry the
    game starts with loads it from folders; ``False`` stands for "not stated",
    never for a "no". *game_folder_scanned* is whether the game's own folder is
    one the emulator scans, ``None`` where that is not established.
    *only_beside_launch* is ``True`` where the game's folder is scanned and
    every folder the emulator scans is scanned only beside the launch, so what
    lies there may not be registered before the game boots. *extensions* are
    the file extensions the emulator reads from those folders, empty where
    none are known.
    """

    offered: bool
    game_folder_scanned: bool | None = None
    only_beside_launch: bool = False
    extensions: tuple[str, ...] = ()


NOT_OFFERED = ExtraContentFolders(offered=False)
