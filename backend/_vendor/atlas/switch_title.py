"""Name a Nintendo Switch game's application id from its content — stdlib only, pure.

A Switch emulator keys a game's saves by the game's **application id**, the
sixteen hex digits the console spells as ``{:016X}``. Content files carry that
id two ways this module reads, and nothing past them:

- **A tag in a file name.** Dumping tools and the libraries built on them name
  a file after its title id in square brackets, ``Game [0100ABCD12340000].nsp``;
  RomM keeps a multi-file game as a folder of such files, the base game beside
  its update and its add-on content. :func:`tagged_title_ids` reads every
  ``[01…]`` tag of sixteen hex digits out of a name. A tag is a convention of
  the file's namer, not a read of the file's bytes — the caller says so.
- **The package's own header.** An NSP (and an NSZ, which keeps the same
  container with compressed entries) is a PFS0 partition filesystem: a
  ``PFS0`` magic, a little-endian entry count and string-table size, four
  bytes of padding, one 0x18-byte entry per file, then the string table of
  file names (``PartitionFilesystem::Header``, ``PFSEntry``,
  ``src/core/file_sys/partition_filesystem.h:40-65``; the read,
  ``partition_filesystem.cpp:25-81`` — eden-emu/eden v0.2.1, 58c1e20e). A
  titlekey-encrypted package carries its ticket as an entry with the ``tik``
  extension (``NSP::SetTicketKeys`` takes every such entry,
  ``submission_package.cpp:186-201``), and the packers name it after its rights
  id, ``<rights id>.tik`` — thirty-two hex digits whose first sixteen are the
  title id, the rights id being the title id followed by the key generation.
  The name is the packer's convention rather than a field the emulator reads,
  so an id read out of it is derived, and the caller says so. :func:`read_pfs0_names` reads the header and the string table and
  nothing else, under a fixed bound; :func:`ticket_title_ids` reads the ids
  out of the names. XCI cartridge images and XCZ keep an HFS0 tree under a
  cartridge header and are not read here: their tag is all there is.

**Normalising to the application.** An update and an add-on carry title ids of
their own, derived from their application's (nxdumptool, ``include/core/title.h``
at DarkMatterCore/nxdumptool@5ca8cd5e: ``titleGetPatchIdByApplicationId`` is
``app_id + 0x800``, ``titleGetAddOnContentBaseIdByApplicationId`` is
``(app_id & ~0xFFF) + 0x1000`` and an add-on's id is that base plus an index
of 1 to 2000, ``TITLE_ADDONCONTENT_MIN_INDEX``/``MAX_INDEX``; a delta fragment
is ``app_id + 0xC00``). An application id's low twelve bits are zero, so the
low twelve bits of any id say which it is, and :func:`application_id` maps
each back. A save is always the application's, so that is the id a caller
keys the save folder by.
"""

from __future__ import annotations

import re
import struct
from typing import BinaryIO, Final

# A tag: sixteen hex digits opening with ``01`` — the range user titles are
# numbered in — between square brackets, either case.
_TITLE_TAG = re.compile(r"\[(01[0-9A-Fa-f]{14})\]")
# A ticket's name: the thirty-two hex digits of its rights id, then ``.tik``.
_TICKET_NAME = re.compile(r"([0-9A-Fa-f]{32})\.tik", re.IGNORECASE)

_PATCH_OFFSET: Final = 0x800
_DELTA_OFFSET: Final = 0xC00
_ADDON_OFFSET: Final = 0x1000
_ADDON_MAX_INDEX: Final = 2000
_LOW_BITS: Final = 0xFFF

PFS0_MAGIC: Final = b"PFS0"
_PFS0_HEADER = struct.Struct("<4sII4x")
_PFS0_ENTRY_SIZE: Final = 0x18
_PFS0_NAME_OFFSET: Final = 0x10
# How much of a package's front this reader takes: the header, one entry per
# file and the string table. A real package lists a handful of files with
# short names, so a header claiming more than this is not one worth reading.
PFS0_HEADER_LIMIT: Final = 1 << 20

# The extensions whose file is a PFS0 package this module opens.
PFS0_EXTENSIONS: Final = (".nsp", ".nsz")


class SwitchPackageUnread(Exception):
    """The bytes are no PFS0 header this reader takes — the wrong magic, or one cut short or past the bound."""


def tagged_title_ids(name: str) -> tuple[int, ...]:
    """Every ``[01…]`` title-id tag in *name*, in order, as numbers."""
    return tuple(int(match, 16) for match in _TITLE_TAG.findall(name))


def ticket_title_ids(names: tuple[str, ...]) -> tuple[int, ...]:
    """The title ids the package's ``<rights id>.tik`` entries name — the rights id's first sixteen hex digits."""
    found: list[int] = []
    for name in names:
        match = _TICKET_NAME.fullmatch(name)
        if match is not None:
            found.append(int(match.group(1)[:16], 16))
    return tuple(found)


def application_id(title_id: int) -> int | None:
    """The application *title_id* belongs to — itself, its patch's or add-on's parent — or ``None``.

    ``None`` is an id whose low twelve bits are none of the four kinds: no
    title this numbering derives, so no application to name.
    """
    low = title_id & _LOW_BITS
    if low == 0:
        return title_id
    if low in (_PATCH_OFFSET, _DELTA_OFFSET):
        return title_id - low
    if low <= _ADDON_MAX_INDEX:
        base = title_id - low
        return None if base < _ADDON_OFFSET else base - _ADDON_OFFSET
    return None


def spelled(application: int) -> str:
    """An application id the way the emulator spells it in a path — ``{:016X}``."""
    return f"{application:016X}"


def read_pfs0_names(f: BinaryIO) -> tuple[str, ...]:
    """The file names a PFS0 package's header lists, in entry order — the header and string table only.

    Raises :class:`SwitchPackageUnread` where the magic is not ``PFS0`` or the
    header is shorter than it says, or larger than :data:`PFS0_HEADER_LIMIT`.
    A name runs to the first NUL from its string-table offset, as the emulator
    reads it.
    """
    head = f.read(_PFS0_HEADER.size)
    if len(head) != _PFS0_HEADER.size:
        raise SwitchPackageUnread("shorter than a PFS0 header")
    magic, count, table_size = _PFS0_HEADER.unpack(head)
    if magic != PFS0_MAGIC:
        raise SwitchPackageUnread("no PFS0 magic")
    entries_size = count * _PFS0_ENTRY_SIZE
    if _PFS0_HEADER.size + entries_size + table_size > PFS0_HEADER_LIMIT:
        raise SwitchPackageUnread("a header larger than the bound")
    body = f.read(entries_size + table_size)
    if len(body) != entries_size + table_size:
        raise SwitchPackageUnread("a header cut short")
    table = body[entries_size:]
    names: list[str] = []
    for index in range(count):
        (offset,) = struct.unpack_from("<I", body, index * _PFS0_ENTRY_SIZE + _PFS0_NAME_OFFSET)
        if offset >= table_size:
            raise SwitchPackageUnread("a name outside the string table")
        end = table.find(b"\0", offset)
        raw = table[offset:] if end < 0 else table[offset:end]
        names.append(raw.decode("utf-8", errors="replace"))
    return tuple(names)
