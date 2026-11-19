"""Read the boot line a PS2 disc image names its game by, the way PCSX2 reads it — stdlib only.

PCSX2 names a running disc by its serial, and the serial is not stored on the
disc as such: ``cdvdGetDiscInfo`` takes the value of the ``BOOT2`` line of the
image's ``SYSTEM.CNF`` (``BOOT`` on a PlayStation disc), the path of the boot
executable, and spells it as a serial (``GetPS2ElfName`` and
``ExecutablePathToSerial``, ``pcsx2/CDVD/CDVD.cpp:471-575``, ``:577-620`` at
PCSX2 v2.8.2, fd9d310c). This module performs the read up to that value and
the spelling after it, and nothing past them.

**Which files are read.** PCSX2 picks a disc's reader by its suffix alone
(``GetFileReader``, ``pcsx2/CDVD/InputIsoFile.cpp:40-57``): ``.chd`` a CHD,
``.cso`` and ``.zso`` a compressed ISO, ``.gz`` a gzipped one, anything else a
flat file — and it offers ``.iso``, ``.bin``, ``.img`` and ``.mdf`` as such
(``VMManager::IsDiscFileName``, ``pcsx2/VMManager.cpp:2443-2454``). Only the
flat files are read here; the four containers are :class:`Ps2DiscFormatNotRead`.
A CHD among them is not cheap to read the way PCSX2 does: a DVD CHD's hunks are
compressed with chdman's general codecs (LZMA, zlib, Huffman, FLAC), two of
which atlas has no decoder for, and PCSX2 finds a parent CHD by its own rule
(``pcsx2/CDVD/ChdFileReader.cpp:210-235``), not the one :mod:`atlas.psx_chd`
follows.

**The sectors.** A flat image's layout is detected by trial
(``InputIsoFile::Detect``, ``InputIsoFile.cpp:272-312``): a block size and a
data offset are tried in PCSX2's order — 2048, 2336, 2352 and 2448 bytes from
offset 0, then 2048, 2352 and 2448 from 150 blocks of 2048 in (an image with a
NERO header) — and the first whose block 16 holds ``CD001`` one byte into its
user data is the image's (``tryIsoType``, :245-265). The user data of a
block begins 24 bytes into the raw sector a block-offset ``blockofs`` was
read to: at once for 2048, 8 bytes in for 2336, 24 for 2352 and 2448
(``ISOreadSector``, ``pcsx2/CDVD/CDVDisoReader.cpp:315-363``). An image of
fewer than 17 blocks of 2048 is none (``Detect`` :281-284), and one where no
layout fits is an audio disc that names no game. A read of a block at or past
the image's block count fails (``ISOreadSector`` :322-323); a short read,
which PCSX2 leaves unchecked, is a failure here.

**SYSTEM.CNF.** ``IsoReader::Open`` takes the first descriptor of type 1 saying
``CD001`` among blocks 16 to 271 (``ReadPVD``, ``pcsx2/CDVD/IsoReader.cpp:45-72``);
a block that cannot be read ends the search. ``ReadFile("SYSTEM.CNF")`` finds the
name in the root directory, every block of it, each record's name cut at its
first ``;`` or NUL and compared without ASCII case, a block's records read
until one shorter than 33 bytes (``LocateFile`` :117-185,
``GetDirectoryEntryFileName`` :88-115); a directory of that name is no file
(``ReadFile`` :282-308). The file is split on ``\\n`` with each line's
surrounding whitespace stripped, and each ``key = value`` line read as
``StringUtil::ParseAssignmentString`` reads it: ``BOOT2`` makes it a PS2 disc,
``BOOT`` a PlayStation one, and the last such line wins (``GetPS2ElfName``).
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import BinaryIO, Final, Literal, Mapping

from ._data import packaged_text

USER_DATA_SIZE: Final = 2048
_PVD_FIRST: Final = 16
_PVD_SEARCH: Final = 256
_PVD_TYPE_PRIMARY: Final = 1
_PVD_IDENTIFIER = slice(1, 6)
_CD001: Final = b"CD001"
_PVD_ROOT_RECORD: Final = 156
_RECORD_HEADER: Final = 33
_RECORD_LOCATION = slice(2, 6)
_RECORD_LENGTH = slice(10, 14)
_RECORD_FLAGS: Final = 25
_RECORD_NAME_LENGTH: Final = 32
_FLAG_DIRECTORY: Final = 0x02
_MIN_BLOCKS: Final = 17
_NERO_OFFSET: Final = 150 * 2048
# (block size, data offset, block offset) in the order Detect tries them.
LAYOUTS: Final = (
    (2048, 0, 24),
    (2336, 0, 16),
    (2352, 0, 0),
    (2448, 0, 0),
    (2048, _NERO_OFFSET, 24),
    (2352, _NERO_OFFSET, 0),
    (2448, _NERO_OFFSET, 0),
)
# The raw-sector offset ISOreadSector copies user data from, before blockofs.
_USER_DATA_AT: Final = 24
SYSTEM_CNF: Final = "SYSTEM.CNF"

# The suffixes PCSX2 opens as a flat image (IsDiscFileName less the ones
# GetFileReader hands another reader), and the ones it opens as a container.
FLAT_SUFFIXES: Final = (".iso", ".bin", ".img", ".mdf")
CONTAINER_SUFFIXES: Final = (".chd", ".cso", ".zso", ".gz")

# atlas's bounds on what one read takes, each far past a real disc's: a root
# directory of a few dozen entries fits a block or two, and a SYSTEM.CNF is a
# handful of lines.
MAX_DIRECTORY_BYTES: Final = 1 << 20
MAX_SYSTEM_CNF_BYTES: Final = 1 << 16

Ps2DiscType = Literal["ps2", "ps1"]
DISC_TYPE_PS2: Ps2DiscType = "ps2"
DISC_TYPE_PS1: Ps2DiscType = "ps1"
_DISC_TYPES: Final = (DISC_TYPE_PS2, DISC_TYPE_PS1)
_BOOT_KEYS: Final[Mapping[str, Ps2DiscType]] = MappingProxyType({"BOOT2": DISC_TYPE_PS2, "BOOT": DISC_TYPE_PS1})

# What C's isspace holds in the "C" locale.
_C_SPACE: Final = " \t\n\v\f\r"
# The shape ExecutablePathToSerial keeps — "????_???.??*" or "????-???.??*",
# matched by StringUtil::WildcardMatch, whose case_sensitive=true branch
# compares through tolower (common/StringUtil.cpp:54-94).
_SERIAL_MASKS: Final = ("????_???.??*", "????-???.??*")
_SERIAL_MASK_PATTERNS: Final = tuple(
    re.compile(fnmatch.translate(mask), re.IGNORECASE | re.ASCII) for mask in _SERIAL_MASKS
)
# Strncasecmp in the C locale folds ASCII letters only.
_ASCII_UPPER: Final = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
# The serial shape a save unit stands behind: four letters, a dash, five digits.
_PRODUCT_SERIAL = re.compile(r"[A-Z]{4}-[0-9]{5}", re.ASCII)


class Ps2DiscUnread(Exception):
    """The bytes name no game: no layout PCSX2 detects, no primary descriptor, no ``SYSTEM.CNF``, no boot line."""


class Ps2DiscFormatNotRead(Exception):
    """A file PCSX2 opens through a container reader (CHD, CSO, ZSO, gzip), or one it does not open as a disc."""


@dataclass(frozen=True, slots=True)
class Ps2DiscFacts:
    """What ``GetPS2ElfName`` keeps of a disc: which line named it, and that line's value as written."""

    disc_type: Ps2DiscType
    boot: str

    def __post_init__(self) -> None:
        if self.disc_type not in _DISC_TYPES:
            raise ValueError(f"Ps2DiscFacts: disc_type must be one of {_DISC_TYPES}, got {self.disc_type!r}")
        if "\0" in self.boot:
            raise ValueError("Ps2DiscFacts: boot is the boot line's value, a string without NUL")


def serial(facts: Ps2DiscFacts) -> str:
    """``ExecutablePathToSerial`` (CDVD.cpp:525-575): ``cdrom0:\\SLUS_201.52;1`` read as ``SLUS-20152``.

    The name after the last ``\\`` — else after the last ``:``, else the whole
    value — cut at its last ``;``; kept only where it matches one of the two
    masks, then every ``.`` dropped, every ``_`` made ``-`` and every other
    character upper-cased in the C locale. A value of no such shape is the
    empty serial, which names no game.
    """
    path = facts.boot
    cut = path.rfind("\\")
    if cut < 0:
        cut = path.rfind(":")
    name = path[cut + 1 :] if cut >= 0 else path
    semicolon = name.rfind(";")
    if semicolon >= 0:
        name = name[:semicolon]
    if not any(pattern.match(name) for pattern in _SERIAL_MASK_PATTERNS):
        return ""
    return "".join("-" if c == "_" else c.upper() if c.isascii() else c for c in name if c != ".")


def is_product_serial(value: str) -> bool:
    """Is *value* a serial of the product-code shape ``SLUS-20152`` — four ASCII uppercase letters, ``-``, five digits?"""
    return _PRODUCT_SERIAL.fullmatch(value) is not None


def product_serial(facts: Ps2DiscFacts) -> str | None:
    """The serial where it is a PS2 disc's and of the product-code shape ``SLUS-20152`` — ``None`` otherwise."""
    if facts.disc_type != DISC_TYPE_PS2:
        return None
    spelled = serial(facts)
    return spelled if is_product_serial(spelled) else None


@lru_cache(maxsize=1)
def _filter_table() -> Mapping[str, tuple[str, ...]]:
    document = json.loads(packaged_text("pcsx2_memcard_filters.json"))
    table: dict[str, tuple[str, ...]] = {}
    for key, filters in document["filters"].items():
        table.setdefault(key.lower(), tuple(filters))
    return MappingProxyType(table)


def memcard_filters(serial: str) -> tuple[str, ...] | None:
    """The ``memcardFilters`` PCSX2's GameDB lists for *serial* — ``None`` where its entry lists none.

    ``GameDatabase::findGame`` looks a serial up lower-cased (GameDatabase.cpp:1074-1080
    at v2.8.2), and where the entry lists filters they replace the serial as the
    folder card's filter (VMManager.cpp:1113, :1161). The table is
    ``atlas/data/pcsx2_memcard_filters.json``, generated from the GameIndex.yaml
    of that revision.
    """
    return _filter_table().get(serial.lower())


def boot_line(system_cnf: bytes) -> tuple[Ps2DiscType, str] | None:
    """``GetPS2ElfName``'s reading of a ``SYSTEM.CNF`` (CDVD.cpp:471-523): the last boot line's kind and value.

    ``SplitString(data, '\\n')`` strips each part and drops the empty ones;
    ``ParseAssignmentString`` splits at the first ``=`` and strips both sides
    (common/StringUtil.cpp:280-302, :324-341). A line with an empty value is
    passed over only where it is the last one. The value is kept byte for
    byte, as a ``std::string`` keeps it.
    """
    text = system_cnf.decode("latin-1")
    lines = [part.strip(_C_SPACE) for part in text.split("\n")]
    lines = [line for line in lines if line]
    found: tuple[Ps2DiscType, str] | None = None
    for number, line in enumerate(lines):
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(_C_SPACE), value.strip(_C_SPACE)
        if not value and number == len(lines) - 1:
            continue
        if key in _BOOT_KEYS:
            found = (_BOOT_KEYS[key], value)
    return found


class _Image:
    """A flat image read through the layout ``Detect`` settled on."""

    def __init__(self, handle: BinaryIO, size: int, layout: tuple[int, int, int]) -> None:
        self._handle = handle
        self._size = size
        self.block_size, self._offset, block_offset = layout
        self._user = _USER_DATA_AT - block_offset
        self._blocks = size // self.block_size

    def user_data(self, lsn: int) -> bytes | None:
        """Block *lsn*'s 2048 bytes of user data — ``None`` past the block count or where the read comes back short."""
        if lsn >= self._blocks:
            return None
        self._handle.seek(self._offset + lsn * self.block_size + self._user)
        data = self._handle.read(USER_DATA_SIZE)
        return data if len(data) == USER_DATA_SIZE else None


def _detect(handle: BinaryIO, size: int) -> _Image:
    if size // USER_DATA_SIZE < _MIN_BLOCKS:
        raise Ps2DiscUnread(f"fewer than {_MIN_BLOCKS} blocks of {USER_DATA_SIZE} bytes, which Detect refuses")
    for layout in LAYOUTS:
        block_size, offset, block_offset = layout
        handle.seek(offset + _PVD_FIRST * block_size + _USER_DATA_AT - block_offset)
        if handle.read(len(_CD001) + 1)[1:] == _CD001:
            return _Image(handle, size, layout)
    raise Ps2DiscUnread("no layout Detect tries holds CD001 at block 16 — an audio disc, which names no game")


def _root(image: _Image) -> tuple[int, int]:
    for index in range(_PVD_SEARCH):
        block = image.user_data(_PVD_FIRST + index)
        if block is None:
            raise Ps2DiscUnread(f"block {_PVD_FIRST + index} cannot be read before a primary descriptor is found")
        if block[_PVD_IDENTIFIER] != _CD001 or block[0] != _PVD_TYPE_PRIMARY:
            continue
        record = block[_PVD_ROOT_RECORD : _PVD_ROOT_RECORD + _RECORD_HEADER + 1]
        return int.from_bytes(record[_RECORD_LOCATION], "little"), int.from_bytes(record[_RECORD_LENGTH], "little")
    raise Ps2DiscUnread(f"no primary descriptor among blocks {_PVD_FIRST} to {_PVD_FIRST + _PVD_SEARCH - 1}")


def _record_name(block: bytes, offset: int, entry_length: int) -> str:
    length = block[offset + _RECORD_NAME_LENGTH]
    if _RECORD_HEADER + length > entry_length or _RECORD_HEADER + length + offset > USER_DATA_SIZE:
        return ""
    raw = block[offset + _RECORD_HEADER : offset + _RECORD_HEADER + length]
    if length == 1 and raw in (b"\0", b"\1"):
        return "." if raw == b"\0" else ".."
    for index, byte in enumerate(raw):
        if byte in (0x3B, 0x00):
            raw = raw[:index]
            break
    return raw.decode("latin-1")


def _locate(image: _Image, location: int, length: int, name: str) -> tuple[int, int, bool] | None:
    """``LocateFile`` of one name in the directory at *location*: its extent, size and directory flag."""
    if length == 0:
        return None
    if length > MAX_DIRECTORY_BYTES:
        raise Ps2DiscUnread(f"a root directory of {length} bytes, past atlas's bound of {MAX_DIRECTORY_BYTES}")
    for index in range((length + USER_DATA_SIZE - 1) // USER_DATA_SIZE):
        block = image.user_data(location + index)
        if block is None:
            return None
        offset = 0
        while offset + _RECORD_HEADER < USER_DATA_SIZE:
            entry_length = block[offset]
            if entry_length < _RECORD_HEADER:
                break
            found = _record_name(block, offset, entry_length)
            record = block[offset : offset + _RECORD_HEADER]
            offset += entry_length
            if found in ("", ".", "..") or found.translate(_ASCII_UPPER) != name.translate(_ASCII_UPPER):
                continue
            return (
                int.from_bytes(record[_RECORD_LOCATION], "little"),
                int.from_bytes(record[_RECORD_LENGTH], "little"),
                bool(record[_RECORD_FLAGS] & _FLAG_DIRECTORY),
            )
    return None


def _read_file(image: _Image, location: int, length: int) -> bytes | None:
    if length > MAX_SYSTEM_CNF_BYTES:
        raise Ps2DiscUnread(f"a SYSTEM.CNF of {length} bytes, past atlas's bound of {MAX_SYSTEM_CNF_BYTES}")
    data = bytearray()
    for index in range((length + USER_DATA_SIZE - 1) // USER_DATA_SIZE):
        block = image.user_data(location + index)
        if block is None:
            return None
        data += block
    return bytes(data[:length])


def suffix_read(path: str) -> bool | None:
    """Is *path* a flat image this module reads (``True``), a container it does not (``False``), or neither (``None``)."""
    lowered = path.lower()
    if lowered.endswith(FLAT_SUFFIXES):
        return True
    if lowered.endswith(CONTAINER_SUFFIXES):
        return False
    return None


def read_facts(handle: BinaryIO, size: int, path: str) -> Ps2DiscFacts:
    """The boot line of the disc image *handle* reads, *size* bytes long and named *path*.

    :class:`Ps2DiscFormatNotRead` where *path*'s suffix is not one of the flat
    images; :class:`Ps2DiscUnread` where the bytes name no game.
    """
    if suffix_read(path) is not True:
        raise Ps2DiscFormatNotRead(f"{path!r} is no flat image PCSX2 opens (.iso, .bin, .img, .mdf)")
    image = _detect(handle, size)
    root_location, root_length = _root(image)
    found = _locate(image, root_location, root_length, SYSTEM_CNF)
    if found is None or found[2]:
        raise Ps2DiscUnread("the root directory holds no SYSTEM.CNF file")
    data = _read_file(image, found[0], found[1])
    if data is None:
        raise Ps2DiscUnread("SYSTEM.CNF runs past the image's blocks")
    line = boot_line(data)
    if line is None:
        raise Ps2DiscUnread("SYSTEM.CNF names no BOOT2 or BOOT line")
    return Ps2DiscFacts(*line)
