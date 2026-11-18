"""Read the titles a Wii U archive (``.wua``) holds, the way Cemu lists them — stdlib only, pure.

Cemu keeps a title's save in the Wii U's internal storage at
``usr/save/<high:08x>/<low:08x>/`` — ``meta/`` beside ``user/<persistent id>/``
and ``user/common/`` — the two words those of the title id the emulator runs
(``ACPMountSaveDir``, ``src/Cafe/OS/libs/nn_acp/nn_acp.cpp:57-69``, and
``_ACPCreateSaveDir``, ``src/Cafe/IOSU/legacy/iosu_acp.cpp:720-748`` — Cemu
2.6, a6fb0a48). This module performs the one read that names that title from
a ``.wua`` file's bytes, and nothing past it.

**The archive.** A ``.wua`` is a ZArchive (Exzap/ZArchive, the submodule Cemu
builds against, ``.gitmodules`` at a6fb0a48; the format is cited at the tag
v0.1.2, whose ``zarchivecommon.h`` is byte-identical to v0.1.0's and to the
current one). Its index is not compressed: only the file data is
zstd-compressed in 64 KiB blocks, so nothing here decompresses anything. The
archive ends in a 144-byte footer (``Footer``, ``zarchivecommon.h:247-300``):
six big-endian ``{u64 offset, u64 size}`` sections — compressed data, offset
records, names, file tree, meta directory, meta data — a 32-byte hash, the
u64 total size, the u32 version ``0x61bf3a01`` and the u32 magic
``0x169f52d6``. The reader opens the file only where the footer's magic and
version are those, the total size is the file's, every section lies inside
the file, the offset records are a non-empty whole number of 40-byte records,
and the file tree a non-empty whole number of 16-byte entries whose first is
an unnamed directory (``ZArchiveReader::OpenFromFile``,
``src/zarchivereader.cpp:29-91``).

**The tree.** Each 16-byte entry is ``nameOffsetAndTypeFlag`` — the high bit
set for a file, the low 31 bits the name's offset into the name table — then
three u32s, for a directory its first child's index and its child count
(``FileDirectoryEntry``, ``zarchivecommon.h:133-245``). A name is a length
byte — its high bit marking a second length byte — and the bytes
(``ZArchiveReader::GetName``, ``zarchivereader.cpp:351-371``, read here as that
code reads it). The root's children are the archive's top level; a child
whose name reads empty is skipped (``GetDirEntry``, :185-205).

**The titles.** Cemu's packer names each title's folder at the top level
``<title id:016x>_v<version>`` (``wxTitleManagerList.cpp:493``), and Cemu reads
a top-level directory as a title exactly where its name is sixteen hex digits
of either case, ``_v``, and a decimal version below 65536 with no leading
zero (``TitleInfo::ParseWuaTitleFolderName``, ``TitleInfo.cpp:143-178``;
``TitleIdParser::ParseFromStr``, ``TitleId.h:86-106``). Launching a ``.wua``
runs a title of a bootable type — base title ``00``, demo ``02``, system
title ``10``, system overlay ``30``, the second byte of the high word
(``TitleIdParser::GetType``, ``TitleId.h:36-60``) — and never an update
(``0e``) or downloadable content (``0c``) (``TitleInfo::DetectFormat``,
``TitleInfo.cpp:217-251``).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Final

FOOTER_SIZE: Final = 144
_FOOTER_MAGIC: Final = 0x169F52D6
_FOOTER_VERSION1: Final = 0x61BF3A01
# The six sections, in footer order: compressed data, offset records, names,
# file tree, meta directory, meta data.
_SECTIONS: Final = 6
_OFFSET_RECORD_SIZE: Final = 8 + 2 * 16
_ENTRY_SIZE: Final = 16
_FILE_FLAG: Final = 0x80000000
_NAME_OFFSET_MASK: Final = 0x7FFFFFFF
_NO_NAME: Final = 0x7FFFFFFF
# The bound on what one archive is asked: the top level holds a title per
# folder, so a few thousand entries is far past any archive Cemu's packer
# writes; a folder name past this many bytes is never a title's
# (<16 hex>_v<5 digits> is 23).
MAX_TOP_LEVEL_ENTRIES: Final = 4096
MAX_NAME_BYTES: Final = 255

# The type byte (bits 32-39 of the id) of the titles a launch boots.
TYPE_BASE: Final = 0x00
TYPE_DEMO: Final = 0x02
TYPE_SYSTEM: Final = 0x10
TYPE_SYSTEM_OVERLAY: Final = 0x30
BOOTABLE_TYPES: Final = frozenset({TYPE_BASE, TYPE_DEMO, TYPE_SYSTEM, TYPE_SYSTEM_OVERLAY})
_U64_MAX: Final = (1 << 64) - 1


class WuaFormatNotRead(Exception):
    """A file with no ZArchive footer at its end — a disc image (``.wud``/``.wux``), a truncated archive, or none."""


class WuaUnread(Exception):
    """A file with a ZArchive footer whose structure Cemu's reader would not open, or past atlas's bound."""


@dataclass(frozen=True, slots=True)
class WuaTitle:
    """One top-level folder Cemu reads as a title: its id and version, from the folder's name."""

    title_id: int
    version: int

    def __post_init__(self) -> None:
        if isinstance(self.title_id, bool) or not 0 <= self.title_id <= _U64_MAX:
            raise ValueError(f"WuaTitle: title_id is a u64, got {self.title_id!r}")
        if isinstance(self.version, bool) or not 0 <= self.version <= 0xFFFF:
            raise ValueError(f"WuaTitle: version is a u16, got {self.version!r}")

    @property
    def type_byte(self) -> int:
        return (self.title_id >> 32) & 0xFF

    @property
    def bootable(self) -> bool:
        """Whether launching the archive may run this title — Cemu's four types, never an update or DLC."""
        return self.type_byte in BOOTABLE_TYPES


@dataclass(frozen=True, slots=True)
class WuaFacts:
    """The archive's top-level title folders, in the archive's own order."""

    titles: tuple[WuaTitle, ...]


def title_words(title_id: int) -> tuple[str, str]:
    """The title id as the save path's two segments: high and low word, 8 lowercase hex each."""
    return f"{title_id >> 32:08x}", f"{title_id & 0xFFFFFFFF:08x}"


def parse_title_folder(name: bytes) -> WuaTitle | None:
    """The title a top-level folder name states, read as ``ParseWuaTitleFolderName`` reads it — or ``None``.

    Sixteen hex digits of either case, then ``_v`` (lowercase ``v`` alone —
    the source compares against ``'v'`` twice), then a decimal version with no
    leading zero; the version accumulates in a u32, and a non-digit, or a
    value past 0xFFFF, refuses the name.
    """
    if len(name) < 16 + 2:
        return None
    try:
        hex_part = name[:16].decode("ascii")
    except UnicodeDecodeError:
        return None
    if any(c not in "0123456789abcdefABCDEF" for c in hex_part):
        return None
    if name[16:18] != b"_v":
        return None
    digits = name[18:]
    if not digits or (digits[:1] == b"0" and len(digits) != 1):
        return None
    version = 0
    for byte in digits:
        version = (version * 10) & 0xFFFFFFFF
        if not 0x30 <= byte <= 0x39:
            version = 0xFFFFFFFF
            break
        version = (version + byte - 0x30) & 0xFFFFFFFF
    if version > 0xFFFF:
        return None
    return WuaTitle(int(hex_part, 16), version)


def read_facts(f: BinaryIO, size: int) -> WuaFacts:
    """Read the top-level title folders of the archive open as *f*, *size* bytes long.

    Raises :class:`WuaFormatNotRead` where the last 144 bytes are no ZArchive
    footer, and :class:`WuaUnread` where the footer is there and the archive
    is one Cemu's reader refuses, or holds more top-level entries than
    :data:`MAX_TOP_LEVEL_ENTRIES`. Reads the footer, the root entry, the root's
    children and each child directory's name — every read bounded.
    """
    if size <= FOOTER_SIZE:
        raise WuaFormatNotRead("shorter than a ZArchive footer")
    footer = _read_exact(f, size - FOOTER_SIZE, FOOTER_SIZE, WuaFormatNotRead)
    total_size, version, magic = struct.unpack_from(">QII", footer, _SECTIONS * 16 + 32)
    if magic != _FOOTER_MAGIC or version != _FOOTER_VERSION1:
        raise WuaFormatNotRead("no ZArchive footer at the end")
    if total_size != size:
        raise WuaUnread(f"the footer states {total_size} bytes; the file is {size}")
    sections = [struct.unpack_from(">QQ", footer, i * 16) for i in range(_SECTIONS)]
    if any(offset + length > size for offset, length in sections):
        raise WuaUnread("a section lies past the end of the file")
    _data, records, names, tree, _meta_dir, _meta = sections
    if records[1] > 0xFFFFFFFF or names[1] > 0x7FFFFFFF or tree[1] > 0xFFFFFFFF:
        raise WuaUnread("a section is larger than the reader takes")
    if records[1] == 0 or records[1] % _OFFSET_RECORD_SIZE:
        raise WuaUnread("the offset records are empty or not whole records")
    if tree[1] == 0 or tree[1] % _ENTRY_SIZE:
        raise WuaUnread("the file tree is empty or not whole entries")
    reader = _Tree(f, names_offset=names[0], names_size=names[1], tree_offset=tree[0], count=tree[1] // _ENTRY_SIZE)
    return WuaFacts(reader.top_level_titles())


def _read_exact(f: BinaryIO, offset: int, count: int, failure: type[Exception]) -> bytes:
    f.seek(offset)
    data = f.read(count)
    if len(data) != count:
        raise failure("the file ends before the bytes its structure states")
    return data


class _Tree:
    """The file tree and name table of an opened archive, read an entry at a time."""

    def __init__(self, f: BinaryIO, *, names_offset: int, names_size: int, tree_offset: int, count: int) -> None:
        self._f = f
        self._names_offset = names_offset
        self._names_size = names_size
        self._tree_offset = tree_offset
        self._count = count

    def top_level_titles(self) -> tuple[WuaTitle, ...]:
        flag, start, children, _reserved = struct.unpack(">IIII", self._entries(0, 1))
        if flag & _FILE_FLAG:
            raise WuaUnread("the first entry is a file, not the root directory")
        if self._name_span(flag & _NAME_OFFSET_MASK) is not None:
            raise WuaUnread("the root directory has a name")
        if children > MAX_TOP_LEVEL_ENTRIES:
            raise WuaUnread(f"{children} top-level entries — more than atlas reads")
        if start + children > self._count:
            raise WuaUnread("the root's children lie past the end of the file tree")
        titles: list[WuaTitle] = []
        block = self._entries(start, children)
        for i in range(children):
            (entry_flag,) = struct.unpack_from(">I", block, i * _ENTRY_SIZE)
            if entry_flag & _FILE_FLAG:
                continue
            name = self._name(entry_flag & _NAME_OFFSET_MASK)
            title = parse_title_folder(name) if name else None
            if title is not None:
                titles.append(title)
        return tuple(titles)

    def _entries(self, index: int, count: int) -> bytes:
        return _read_exact(self._f, self._tree_offset + index * _ENTRY_SIZE, count * _ENTRY_SIZE, WuaUnread)

    def _name_span(self, offset: int) -> tuple[int, int] | None:
        """Where the name at *offset* lies in the table and how long it is — ``None`` where it reads empty.

        ``GetName``'s reading, extended-length branch included: that branch
        ORs the first length byte, shifted, into the length, and skips two.
        """
        if offset == _NO_NAME or offset > self._names_size or offset == self._names_size:
            return None
        header = _read_exact(self._f, self._names_offset + offset, 1, WuaUnread)[0]
        length = header & 0x7F
        if header & 0x80:
            if offset + 1 >= self._names_size:
                return None
            length = (length | (header << 7)) & 0xFFFF
            offset += 2
        else:
            offset += 1
        if offset + length > self._names_size or length == 0:
            return None
        return offset, length

    def _name(self, offset: int) -> bytes:
        """The name at *offset*, or ``b""`` where it reads empty or is longer than any title folder's could be."""
        span = self._name_span(offset)
        if span is None or span[1] > MAX_NAME_BYTES:
            return b""
        return _read_exact(self._f, self._names_offset + span[0], span[1], WuaUnread)
