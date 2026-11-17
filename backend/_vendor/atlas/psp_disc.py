"""Read what PPSSPP reads of a PSP disc image to key its saves — stdlib only, pure.

A PSP game keeps its saves on the memory stick, in folders directly below
``PSP/SAVEDATA`` whose names begin with a name the game hands the savedata
utility — ``gameName``, joined with the save's own name and nothing between
(``SavedataParam::GetSaveDir``, ``Core/Dialog/SavedataParam.cpp:238-245``;
``GetGameName`` takes the field from the game's own request, :269-272 —
hrydgard/ppsspp v1.20.4, fa50bb19). The emulator does not derive that name: a
game spells it, by the platform's convention its own product code, the
``DISC_ID`` its disc's ``PARAM.SFO`` states. This module performs the two reads
that establish those facts from bytes, and nothing past them.

**The disc's id.** PPSSPP takes a disc's identity from
``disc0:/PSP_GAME/PARAM.SFO`` (``LoadParamSFOFromDisc``,
``Core/PSPLoaders.cpp:129-141``) and its ``DISC_ID`` string
(``ParamSFOData::GetValueString``, ``Core/ELF/ParamSFO.cpp:75-80``).
``UMD_DATA.BIN`` is read only to tell an HD remaster apart (:145-179), so it
is not read here. The image is opened by its first bytes
(``ConstructBlockDevice``, ``Core/FileSystems/BlockDevices.cpp:222-262``):
``CISO`` is a compressed ISO, ``\\0PBP`` an EBOOT, ``MComprHD`` a CHD, and
anything else a plain image of 2048-byte blocks. Only the plain image is read
here; the other three are a container PPSSPP opens and this reader does not
(:class:`PspDiscFormatNotRead`). On a plain image the volume descriptor is
block 16, which must say ``CD001`` (``ISOFileSystem::ISOFileSystem``,
``Core/FileSystems/ISOFileSystem.cpp:152-180``); its root directory record
leads to ``PSP_GAME`` and then ``PARAM.SFO``, each name compared exactly once
its ``;`` version is cut (``CleanISOFileName`` :142-148, ``ReadDirectory``
:196-265, ``GetFromPath`` :267-330). The id is normalised to the nine
characters a savedata folder begins with: a ``-`` after the four letters, as
``UMD_DATA.BIN`` spells it, is dropped (``DetectGameRegionFromID`` accepts both,
``ParamSFO.cpp:353-354``), and an id that is not four letters and five digits
is no product code this reader names (:func:`game_id`).

**A savedata folder's PARAM.SFO.** Every savedata write sets
``SAVEDATA_FILE_LIST`` and ``SAVEDATA_PARAMS`` in the folder's ``PARAM.SFO``
(``SavedataParam.cpp:533``, :538), while a game-data install — the utility
that copies a disc's ``INSDIR`` into ``PSP/SAVEDATA/<gameName><dataName>`` —
writes its ``PARAM.SFO`` with neither (``PSPGamedataInstallDialog::WriteSfoFile``,
``Core/Dialog/PSPGamedataInstallDialog.cpp:211-243``). ``CATEGORY`` does not
tell them apart: both write ``MS`` (``SavedataParam.cpp:505``,
``PSPGamedataInstallDialog.cpp:225``). :func:`parse_sfo_keys` reads the keys
the way ``ParamSFOData::ReadSFO`` keeps them (``ParamSFO.cpp:121-203``).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from collections.abc import Iterator
from typing import BinaryIO, Final, Literal

BLOCK_SIZE: Final = 2048
_PVD_BLOCK: Final = 16
_PVD_IDENTIFIER = slice(1, 6)
_PVD_ROOT_RECORD: Final = 156
_RECORD_HEADER: Final = 33
_RECORD_FLAGS: Final = 25
_RECORD_NAME_LENGTH: Final = 32
_FLAG_DIRECTORY: Final = 0x02

# The magics ConstructBlockDevice opens as something other than a plain image.
_CISO_MAGIC: Final = b"CISO"
_PBP_MAGIC: Final = b"\x00PBP"
_CHD_MAGIC: Final = b"MComprHD"

# atlas's bounds on what one read takes, each far past a real disc's: a
# directory of a few dozen entries fits one block, and PSP_GAME/PARAM.SFO and
# a savedata folder's are a few kilobytes.
MAX_DIRECTORY_BYTES: Final = 1 << 20
MAX_SFO_BYTES: Final = 1 << 16

_SFO_MAGIC: Final = 0x46535000
_SFO_HEADER = struct.Struct("<IIIII")
_SFO_INDEX = struct.Struct("<HHIII")
_SFO_INT: Final = 0x0404
_SFO_SPECIAL: Final = 0x0004
_SFO_STRING: Final = 0x0204

_GAME_ID = re.compile(r"[A-Z]{4}[0-9]{5}")
GAME_ID_LENGTH: Final = 9
# The savedata keys a write sets and an install does not.
SAVEDATA_KEYS: Final = ("SAVEDATA_FILE_LIST", "SAVEDATA_PARAMS")

PspContainer = Literal["iso"]
CONTAINER_ISO: PspContainer = "iso"


class PspDiscUnread(Exception):
    """The bytes are no PSP disc this reader takes — no ``CD001``, no ``PSP_GAME/PARAM.SFO``, no ``DISC_ID``."""


class PspDiscFormatNotRead(Exception):
    """A container PPSSPP opens and this reader does not — CSO, an EBOOT (PBP) or a CHD."""


class SfoUnread(Exception):
    """The bytes are no ``PARAM.SFO`` ``ReadSFO`` keeps — a wrong magic, a table past the end, past the bound."""


@dataclass(frozen=True, slots=True)
class PspDiscFacts:
    """What PPSSPP reads of a disc to name it: the container, and ``DISC_ID`` as the disc spells it."""

    container: PspContainer
    disc_id: str

    def __post_init__(self) -> None:
        if self.container != CONTAINER_ISO:
            raise ValueError(f"PspDiscFacts: container must be {CONTAINER_ISO!r}, got {self.container!r}")
        if not self.disc_id or "\0" in self.disc_id:
            raise ValueError("PspDiscFacts: disc_id is the non-empty string DISC_ID states")


def game_id(facts: PspDiscFacts) -> str | None:
    """The nine-character product code a savedata folder of this disc begins with — ``None`` where it is none.

    ``ULUS10064`` as it stands; ``ULUS-10064`` without its dash. Anything
    else — a homebrew's own id, an id of another shape — names no folder this
    reader can stand behind.
    """
    spelled = facts.disc_id
    if len(spelled) == GAME_ID_LENGTH + 1 and spelled[4] == "-":
        spelled = spelled[:4] + spelled[5:]
    return spelled if _GAME_ID.fullmatch(spelled) else None


def parse_sfo(data: bytes) -> dict[str, str | int | bytes]:
    """The values a ``PARAM.SFO`` holds, kept the way ``ReadSFO`` keeps them.

    An entry whose key or data starts past the end refuses the whole table, as
    in the emulator; an entry with an empty key, a format it does not know, or
    an integer or special value running past the end is skipped. A string
    runs to its first NUL, at most ``param_max_len`` long.
    """
    key_start, data_start, count = _sfo_header(data)
    values: dict[str, str | int | bytes] = {}
    for index in range(count):
        entry = _sfo_entry(data, _SFO_HEADER.size + index * _SFO_INDEX.size, key_start, data_start)
        if entry is not None:
            values[entry[0]] = entry[1]
    return values


def _sfo_header(data: bytes) -> tuple[int, int, int]:
    """The key table's start, the data table's start and the entry count — or :class:`SfoUnread`."""
    if len(data) > MAX_SFO_BYTES:
        raise SfoUnread(f"a PARAM.SFO of {len(data)} bytes, past atlas's bound of {MAX_SFO_BYTES}")
    if len(data) < _SFO_HEADER.size:
        raise SfoUnread("shorter than a PARAM.SFO header")
    magic, _version, key_start, data_start, count = _SFO_HEADER.unpack_from(data)
    if magic != _SFO_MAGIC:
        raise SfoUnread("no PSF magic")
    if key_start > len(data) or data_start > len(data):
        raise SfoUnread("a table starting past the end")
    if _SFO_HEADER.size + count * _SFO_INDEX.size > len(data):
        raise SfoUnread("an index running past the end")
    return key_start, data_start, count


def _sfo_entry(data: bytes, at: int, key_start: int, data_start: int) -> tuple[str, str | int | bytes] | None:
    """The key and value of the index entry at *at* — ``None`` where ``ReadSFO`` skips it."""
    key_offset, fmt, length, max_length, data_offset = _SFO_INDEX.unpack_from(data, at)
    key_at, value_at = key_start + key_offset, data_start + data_offset
    if key_at >= len(data) or value_at >= len(data):
        raise SfoUnread("an entry past the end")
    key = _c_string(data, key_at, 0)
    if not key:
        return None
    if fmt == _SFO_INT and value_at + 4 <= len(data):
        return key, struct.unpack_from("<I", data, value_at)[0]
    if fmt == _SFO_SPECIAL and value_at + length <= len(data):
        return key, data[value_at : value_at + length]
    if fmt == _SFO_STRING:
        return key, _c_string(data, value_at, max_length)
    return None


def parse_sfo_keys(data: bytes) -> frozenset[str]:
    """The keys a ``PARAM.SFO`` holds once ``ReadSFO`` has kept its entries (:func:`parse_sfo`)."""
    return frozenset(parse_sfo(data))


def is_savedata(keys: frozenset[str]) -> bool:
    """Does a savedata folder's ``PARAM.SFO`` carry a key only a savedata write sets?"""
    return any(key in keys for key in SAVEDATA_KEYS)


def _c_string(data: bytes, offset: int, cap: int) -> str:
    end = data.find(b"\0", offset)
    raw = data[offset:] if end < 0 else data[offset:end]
    if cap:
        raw = raw[:cap]
    return raw.decode("utf-8", errors="replace")


def read_facts(f: BinaryIO) -> PspDiscFacts:
    """The disc's container and ``DISC_ID``, read from *f*'s bytes the way PPSSPP reads them.

    Raises :class:`PspDiscFormatNotRead` for a CSO, PBP or CHD and
    :class:`PspDiscUnread` for a plain image this reader does not take.
    """
    head = f.read(8)
    if len(head) != 8:
        raise PspDiscUnread("shorter than the eight bytes the emulator opens an image by")
    if head.startswith(_CISO_MAGIC) or head.startswith(_PBP_MAGIC) or head == _CHD_MAGIC:
        raise PspDiscFormatNotRead(f"a container opened by its magic {head[:4]!r}, which this reader does not read")
    descriptor = _block(f, _PVD_BLOCK)
    if descriptor[_PVD_IDENTIFIER] != b"CD001":
        raise PspDiscUnread("no CD001 volume descriptor at block 16")
    root = _record_at(descriptor, _PVD_ROOT_RECORD)
    if root is None:
        raise PspDiscUnread("no root directory record")
    game = _find(f, root, "PSP_GAME", want_directory=True)
    sfo = _find(f, game, "PARAM.SFO", want_directory=False)
    lba, size = sfo
    if size > MAX_SFO_BYTES:
        raise PspDiscUnread(f"a PARAM.SFO of {size} bytes, past atlas's bound of {MAX_SFO_BYTES}")
    f.seek(lba * BLOCK_SIZE)
    data = f.read(size)
    if len(data) != size:
        raise PspDiscUnread("PSP_GAME/PARAM.SFO runs past the end of the image")
    try:
        disc_id = parse_sfo(data).get("DISC_ID")
    except SfoUnread as error:
        raise PspDiscUnread(f"PSP_GAME/PARAM.SFO: {error}") from error
    if not isinstance(disc_id, str) or not disc_id:
        raise PspDiscUnread("PSP_GAME/PARAM.SFO states no DISC_ID string")
    return PspDiscFacts(CONTAINER_ISO, disc_id)


def _block(f: BinaryIO, lba: int) -> bytes:
    f.seek(lba * BLOCK_SIZE)
    data = f.read(BLOCK_SIZE)
    if len(data) != BLOCK_SIZE:
        raise PspDiscUnread(f"block {lba} runs past the end of the image")
    return data


def _record_at(block: bytes, offset: int) -> tuple[int, int] | None:
    """The extent (first block, byte length) of the directory record at *offset* — ``None`` where it is empty."""
    if offset + _RECORD_HEADER > len(block) or block[offset] == 0:
        return None
    lba, size = struct.unpack_from("<I4xI", block, offset + 2)
    return lba, size


def _find(f: BinaryIO, parent: tuple[int, int], name: str, *, want_directory: bool) -> tuple[int, int]:
    """The extent of the entry *name* directly in the directory *parent* — the first whose cleaned name is *name*.

    Names are compared exactly once the ``;`` version is cut, as in the
    emulator. The entry found must be of the kind asked for.
    """
    wanted = name.encode("ascii")
    for raw, is_directory, extent in _records(f, parent):
        if raw.split(b";", 1)[0] != wanted:
            continue
        if is_directory != want_directory:
            raise PspDiscUnread(f"{name} is not a {'directory' if want_directory else 'file'}")
        return extent
    raise PspDiscUnread(f"no {name} in its directory")


def _records(f: BinaryIO, parent: tuple[int, int]) -> Iterator[tuple[bytes, bool, tuple[int, int]]]:
    """Each record of the directory *parent*: its raw name, whether it is a directory, and its extent.

    A record runs to its length byte; a zero length ends the block's records,
    and one whose name would cross the block refuses the directory.
    """
    lba, size = parent
    if size > MAX_DIRECTORY_BYTES:
        raise PspDiscUnread(f"a directory of {size} bytes, past atlas's bound of {MAX_DIRECTORY_BYTES}")
    for block_index in range((size + BLOCK_SIZE - 1) // BLOCK_SIZE):
        block = _block(f, lba + block_index)
        offset = 0
        while offset < BLOCK_SIZE and block[offset] != 0:
            yield _record(block, offset)
            offset += block[offset]


def _record(block: bytes, offset: int) -> tuple[bytes, bool, tuple[int, int]]:
    """The record at *offset*: its raw name, whether it is a directory, and its extent — or :class:`PspDiscUnread`."""
    if block[offset] < _RECORD_HEADER or offset + _RECORD_HEADER > BLOCK_SIZE:
        raise PspDiscUnread("a directory record shorter than its header, or crossing its block")
    name_length = block[offset + _RECORD_NAME_LENGTH]
    if offset + _RECORD_HEADER + name_length > BLOCK_SIZE:
        raise PspDiscUnread("a directory record crossing its block")
    raw = block[offset + _RECORD_HEADER : offset + _RECORD_HEADER + name_length]
    lba, size = struct.unpack_from("<I4xI", block, offset + 2)
    return raw, bool(block[offset + _RECORD_FLAGS] & _FLAG_DIRECTORY), (lba, size)
