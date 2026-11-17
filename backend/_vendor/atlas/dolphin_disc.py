"""Read what Dolphin reads of a GameCube or Wii disc image to key its saves — stdlib only.

Dolphin keys a game's saves by what the disc says about itself: a GameCube
game is given the ``.gci`` files of a GCI folder whose header carries its
game code, in the folder for its region, and a Wii game saves below its title
id in the NAND. This module performs the reads that establish those three
facts from an image's bytes, through the same container readers Dolphin opens
the image with, and nothing past them. Every source named here is
dolphin-emu/dolphin at the 2609 release (b134d026), the build the standalone
save card pins; the container formats are file formats, so the layouts read
here are the files' and not one build's.

**Which container.** ``CreateBlobReader`` switches on the file's first four
bytes and takes anything else as a plain image (``DiscIO/Blob.cpp:215-251``):

- **plain** — ISO, GCM and NKit images alike: the disc's bytes as they are
  (``FileBlob.cpp``).
- **CISO** — magic ``CISO``, a little-endian block size at 4 and a map of
  ``0x7FF8`` bytes from 8, one byte per block; a block whose byte is 1 is
  stored, in map order, after the ``0x8000``-byte header, and any other block
  reads as zeros (``CISOBlob.h:15-29``, ``CISOBlob.cpp:15-27``, :55-85).
- **GCZ** — magic ``0xB10BC001`` little-endian, a 32-byte header (sub-type,
  compressed data size, disc size, block size, block count), then one ``u64``
  pointer per block — the top bit set where the block is stored raw — and one
  ``u32`` hash per block, then the data; a stored block is one zlib stream
  that must inflate to exactly the block size (``CompressedBlob.h:25-41``,
  ``CompressedBlob.cpp:44-97``, :123-211). Only the blocks a read touches are
  inflated.
- **WBFS** — magic ``WBFS``, the sector count big-endian at 4, the two sector
  shifts at 8 and 9 and the disc table from 12, whose first byte must be set;
  the disc's info sits one HD sector in: a 256-byte copy of the disc header,
  then one big-endian ``u16`` per WBFS sector of the disc naming where that
  sector is stored (``WbfsBlob.h:16``, :69-78; ``WbfsBlob.cpp:23-45``,
  :93-120, :148-179). Reads go through that table, as Dolphin's do; a split
  set's later parts (``.wbf1`` …) are not opened, so a read landing in one is
  not exposed.
- **WIA and RVZ** — magic ``WIA\\x01`` / ``RVZ\\x01``, a 0x48-byte first
  header whose own SHA-1 closes it, then the second header whose 0x80-byte
  ``disc_header`` is the disc's first 0x80 bytes, uncompressed
  (``WIABlob.h:40-41``, :81-119; ``WIABlob.cpp:92-140``). Dolphin answers a
  read of those bytes from that copy (:318-332); everything past them is in
  compressed groups this reader does not open, so a WIA or RVZ image exposes
  the disc header and nothing else.

TGC, NFS, an extracted directory and any file shorter than a disc header are
no image this reader takes (:class:`DolphinDiscUnread`).

**Which disc.** ``TryCreateDisc`` takes a Wii disc by ``0x5D1C9EA3`` at 0x18
and a GameCube disc by ``0xC2339F3D`` at 0x1C (``Volume.cpp:112-129``,
``DiscUtils.h:25-26``). The game id is the six bytes at 0
(``VolumeDisc.cpp:56-59``), which Dolphin filters to ASCII letters and digits,
every other byte becoming ``-`` (``Volume.cpp:46-56``); the revision is the
byte at 7 (``VolumeDisc.cpp:144-148``) and the country code the byte at 3.

**The GameCube region** is the big-endian ``u32`` at 0x458
(``VolumeGC.cpp:91-108``), a :class:`Region` value where it is at most
NTSC-K and Unknown otherwise (``VolumeDisc.cpp:102-109``, ``Enums.h:45-53``).
Where the container does not expose 0x458 — WIA and RVZ — the country code
stands in, read through ``CountryCodeToRegion`` (``Enums.cpp:213-280``), the
mapping Dolphin's verifier holds a disc's region against
(``VolumeVerifier.cpp:915-920``): that is derived, not what the emulator reads,
and :func:`gamecube_region` says which of the two it answered from. A country
code whose region the mapping takes from the region code it is checked
against — ``W``, ``X``, ``Y``, ``Z`` and the Wii Menu's ``\\x02`` — establishes
nothing.

**The Wii title id** is the game partition's ticket's: the partition table at
0x40000 lists up to four groups of ``(offset >> 2, type)`` entries, the game
partition is the first of type 0 in group order, and its ticket is the first
``0x2A4`` bytes of the partition (``VolumeWii.cpp:50-84``,
``DiscUtils.h:39-40``), unencrypted, whose big-endian title id sits at 0x1DC
(``Core/IOS/ES/Formats.h:131-152`` packed at 4, ``IOSC.h:50-57``) and which
is valid where its signature type is one ES knows and it is a v0 ticket
(``Formats.cpp:112-124``, :153-166, :368-377). ``VolumeWii::GetTitleID``
answers it (``VolumeWii.cpp:270-276``). A container that does not expose the
partition — WIA and RVZ — leaves it unread.
"""

from __future__ import annotations

import hashlib
import os
import struct
import zlib
from dataclasses import dataclass
from typing import BinaryIO, Callable, Final, Literal

Container = Literal["plain", "ciso", "gcz", "wbfs", "wia", "rvz"]
CONTAINER_PLAIN: Container = "plain"
CONTAINER_CISO: Container = "ciso"
CONTAINER_GCZ: Container = "gcz"
CONTAINER_WBFS: Container = "wbfs"
CONTAINER_WIA: Container = "wia"
CONTAINER_RVZ: Container = "rvz"
CONTAINERS: tuple[Container, ...] = (
    CONTAINER_PLAIN,
    CONTAINER_CISO,
    CONTAINER_GCZ,
    CONTAINER_WBFS,
    CONTAINER_WIA,
    CONTAINER_RVZ,
)

DiscPlatform = Literal["gc", "wii"]
PLATFORM_GC: DiscPlatform = "gc"
PLATFORM_WII: DiscPlatform = "wii"
DISC_PLATFORMS: tuple[DiscPlatform, ...] = (PLATFORM_GC, PLATFORM_WII)

# Where a GameCube region was read from: the region code the emulator reads,
# or the country code standing in for it where the container hides the code.
RegionBasis = Literal["region-code", "country-code"]
REGION_BASIS_REGION_CODE: RegionBasis = "region-code"
REGION_BASIS_COUNTRY_CODE: RegionBasis = "country-code"

GAME_ID_LENGTH: Final = 6
# The bytes every disc this reader takes holds before anything else is asked.
_DISC_HEADER_READ: Final = 0x20
_WII_MAGIC_OFFSET: Final = 0x18
_GC_MAGIC_OFFSET: Final = 0x1C
_WII_DISC_MAGIC: Final = 0x5D1C9EA3
_GC_DISC_MAGIC: Final = 0xC2339F3D
_REVISION_OFFSET: Final = 7
_COUNTRY_OFFSET: Final = 3
_GC_REGION_OFFSET: Final = 0x458

# ``DiscIO::Region`` (Enums.h:45-53): the three a GameCube card is filed
# under, as Dolphin numbers them, and the Korean one it files under NTSC-J.
REGION_NTSC_J: Final = 0
REGION_NTSC_U: Final = 1
REGION_PAL: Final = 2
_REGION_NTSC_K: Final = 4

_CISO_MAGIC: Final = b"CISO"
_CISO_HEADER_SIZE: Final = 0x8000
_CISO_MAP_SIZE: Final = _CISO_HEADER_SIZE - 8

_GCZ_MAGIC: Final = 0xB10BC001
_GCZ_HEADER = struct.Struct("<IIQQII")
_GCZ_UNCOMPRESSED: Final = 1 << 63
# Dolphin sizes its inflate buffer at the block size plus this margin and
# refuses a stored block larger than that (CompressedBlob.cpp:92, :156-160).
_GCZ_ZLIB_MARGIN: Final = 64
# A block this reader will inflate at most: no image Dolphin writes uses
# blocks anywhere near it, and a header naming a larger one is read as no
# disc rather than as an allocation the header chose.
_GCZ_BLOCK_LIMIT: Final = 1 << 24

_WBFS_MAGIC: Final = b"WBFS"
_WBFS_HEADER = struct.Struct(">4sIBB2xB")
_WII_SECTOR_SIZE: Final = 0x8000
_WII_DISC_SIZE: Final = 143432 * 2 * _WII_SECTOR_SIZE
_WBFS_DISC_HEADER_SIZE: Final = 256

_WIA_MAGIC: Final = b"WIA\x01"
_RVZ_MAGIC: Final = b"RVZ\x01"
_WIA_HEADER_1 = struct.Struct(">4sIII20sQQ20s")
_WIA_HEADER_1_HASHED: Final = _WIA_HEADER_1.size - 20
# ``sizeof(WIAHeader2) - sizeof(compressor_data)`` (WIABlob.cpp:130-132), and
# where the disc header copy sits inside it (WIABlob.h:94-101).
_WIA_HEADER_2_MINIMUM: Final = 0xDC - 7
_WIA_DISC_HEADER_OFFSET: Final = 0x10
_WIA_DISC_HEADER_SIZE: Final = 0x80
# ``WIA_VERSION`` / ``RVZ_VERSION`` and their read-compatible floors
# (WIABlob.h:391-397), held against the file's the way Initialize holds them
# (WIABlob.cpp:103-114).
_WIA_VERSIONS: Final = {
    _WIA_MAGIC: (0x01000000, 0x00080000),
    _RVZ_MAGIC: (0x01000000, 0x00030000),
}

_PARTITION_TABLE: Final = 0x40000
_PARTITION_GROUPS: Final = 4
# No disc lists more than a handful of partitions; a table naming more is
# read up to this many entries per group rather than for as long as it says.
_PARTITION_LIMIT: Final = 64
_GAME_PARTITION_TYPE: Final = 0
_TICKET_SIZE: Final = 0x2A4
_TICKET_VERSION_OFFSET: Final = 0x1BC
_TICKET_TITLE_ID_OFFSET: Final = 0x1DC
# ``SignatureType`` (IOSC.h:26-31): RSA4096, RSA2048, ECC.
_SIGNATURE_TYPES: Final = frozenset({0x00010000, 0x00010001, 0x00010002})

# ``CountryCodeToRegion`` for a GameCube disc (Enums.cpp:213-280), keyed by
# the country byte; ``E`` turns on the revision and is decided apart.
_COUNTRY_REGIONS: Final = {
    **dict.fromkeys(b"J", REGION_NTSC_J),
    **dict.fromkeys(b"BN", REGION_NTSC_U),
    **dict.fromkeys(b"DFHILMPRSUV", REGION_PAL),
    # Korean country codes: NTSC-K does not exist on GameCube (Enums.cpp:272-276).
    **dict.fromkeys(b"KQT", REGION_NTSC_J),
}
_COUNTRY_E: Final = ord("E")
# A GameCube ``E`` disc at this revision or later is a Korean disc in English
# (Enums.cpp:230-240).
_KOREAN_ENGLISH_REVISION: Final = 0x30


class DolphinDiscUnread(Exception):
    """The bytes are no GameCube or Wii disc image this reader takes."""


@dataclass(frozen=True, slots=True)
class DolphinDiscFacts:
    """What a disc image's bytes say about the disc, read through the image's container.

    ``game_id`` is the six bytes at disc offset 0, one character per byte
    (latin-1) and unfiltered; :attr:`dolphin_game_id` is it the way Dolphin
    spells it. ``region_code`` is the GameCube region code at 0x458 and
    ``title_id`` the Wii game partition's ticket's title id, each ``None``
    where the disc is the other platform's or the container does not expose
    the bytes.
    """

    container: Container
    platform: DiscPlatform
    game_id: str
    revision: int
    region_code: int | None = None
    title_id: int | None = None

    def __post_init__(self) -> None:
        if self.container not in CONTAINERS:
            raise ValueError(f"DolphinDiscFacts: container must be one of {CONTAINERS}, got {self.container!r}")
        if self.platform not in DISC_PLATFORMS:
            raise ValueError(f"DolphinDiscFacts: platform must be one of {DISC_PLATFORMS}, got {self.platform!r}")
        if len(self.game_id) != GAME_ID_LENGTH or any(ord(char) > 0xFF for char in self.game_id):
            raise ValueError(f"DolphinDiscFacts: game_id is six one-byte characters, got {self.game_id!r}")
        if not 0 <= self.revision <= 0xFF:
            raise ValueError(f"DolphinDiscFacts: revision is one byte, got {self.revision!r}")
        if self.region_code is not None and (self.platform != PLATFORM_GC or not 0 <= self.region_code <= 0xFFFFFFFF):
            raise ValueError("DolphinDiscFacts: a region code is a GameCube disc's u32")
        if self.title_id is not None and (self.platform != PLATFORM_WII or not 0 <= self.title_id < 1 << 64):
            raise ValueError("DolphinDiscFacts: a title id is a Wii disc's u64")

    @property
    def dolphin_game_id(self) -> str:
        """The game id as ``FilterGameID`` leaves it: ASCII letters and digits, anything else ``-``."""
        return "".join(char if char.isascii() and char.isalnum() else "-" for char in self.game_id)

    @property
    def game_code(self) -> str:
        """The first four characters of :attr:`dolphin_game_id` — what a ``.gci`` header is compared with."""
        return self.dolphin_game_id[:4]


@dataclass(frozen=True, slots=True)
class GameCubeRegion:
    """A GameCube disc's region, and whether the region code or the country code stated it.

    ``region`` is Dolphin's own number for it: :data:`REGION_NTSC_J`,
    :data:`REGION_NTSC_U` or :data:`REGION_PAL`.
    """

    region: int
    basis: RegionBasis


def gamecube_region(facts: DolphinDiscFacts) -> GameCubeRegion | None:
    """The region Dolphin files a GameCube disc's card under — ``None`` where the bytes do not establish one.

    The region code where the container exposed it: NTSC-J, NTSC-U and PAL as
    they are, NTSC-K as NTSC-J (``ToGameCubeRegion``,
    ``Core/Config/MainSettings.cpp:721-729``), and Unknown — which Dolphin
    replaces with the configured fallback region (``ConfigManager.cpp:489-490``)
    — or any other value as nothing established. Without the region code, the
    country code's region where the mapping states one on its own.
    """
    if facts.platform != PLATFORM_GC:
        return None
    if facts.region_code is not None:
        region = {
            REGION_NTSC_J: REGION_NTSC_J,
            REGION_NTSC_U: REGION_NTSC_U,
            REGION_PAL: REGION_PAL,
            _REGION_NTSC_K: REGION_NTSC_J,
        }.get(facts.region_code)
        return None if region is None else GameCubeRegion(region, REGION_BASIS_REGION_CODE)
    country = ord(facts.game_id[_COUNTRY_OFFSET])
    if country == _COUNTRY_E:
        english = REGION_NTSC_J if facts.revision >= _KOREAN_ENGLISH_REVISION else REGION_NTSC_U
        return GameCubeRegion(english, REGION_BASIS_COUNTRY_CODE)
    mapped = _COUNTRY_REGIONS.get(country)
    return None if mapped is None else GameCubeRegion(mapped, REGION_BASIS_COUNTRY_CODE)


def title_words(title_id: int) -> tuple[str, str]:
    """A title id's two words as Dolphin spells them in the NAND: eight lowercase hex digits each."""
    return f"{title_id >> 32:08x}", f"{title_id & 0xFFFFFFFF:08x}"


def game_code_word(facts: DolphinDiscFacts) -> str:
    """The low word a disc title's id carries: its game code's four bytes, as eight lowercase hex digits.

    A disc title's low word is its four-character game code — Dolphin reads
    those four bytes of a title id as the GameTDB id wherever they are letters
    and digits (``TMDReader::GetGameTDBID``, ``Core/IOS/ES/Formats.cpp:307-313``)
    — so where the ticket was not read this names the low word, and the high
    word, the title's category, is not stated by it (``TitleType``,
    ``Formats.h:33-41``: a disc that installs a channel is ``00010004``, not
    :data:`DISC_TITLE_HIGH_WORD`).
    """
    return facts.game_id[:4].encode("latin-1").hex()


# ``TitleType::Game`` (Core/IOS/ES/Formats.h:33-41): the category of a disc
# title's id, the high word a disc that installs no channel carries.
DISC_TITLE_HIGH_WORD: Final = "00010000"

_Read = Callable[[int, int], "bytes | None"]


def read_facts(f: BinaryIO) -> DolphinDiscFacts:
    """The disc facts of the image open in *f* — :class:`DolphinDiscUnread` where it is none this reader takes.

    An ``OSError`` from the file itself is left to the caller.
    """
    size = f.seek(0, os.SEEK_END)
    container, read = _container(f, size)
    header = read(0, _DISC_HEADER_READ)
    if header is None or len(header) != _DISC_HEADER_READ:
        raise DolphinDiscUnread("no disc header")
    if _u32(header, _WII_MAGIC_OFFSET) == _WII_DISC_MAGIC:
        platform = PLATFORM_WII
    elif _u32(header, _GC_MAGIC_OFFSET) == _GC_DISC_MAGIC:
        platform = PLATFORM_GC
    else:
        raise DolphinDiscUnread("neither disc magic")
    game_id = header[:GAME_ID_LENGTH].decode("latin-1")
    revision = header[_REVISION_OFFSET]
    if platform == PLATFORM_GC:
        code = read(_GC_REGION_OFFSET, 4)
        region_code = _u32(code, 0) if code is not None and len(code) == 4 else None
        return DolphinDiscFacts(container, platform, game_id, revision, region_code=region_code)
    return DolphinDiscFacts(container, platform, game_id, revision, title_id=_ticket_title_id(read))


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def _read_exactly(f: BinaryIO, offset: int, length: int) -> bytes | None:
    f.seek(offset)
    data = f.read(length)
    return data if len(data) == length else None


def _container(f: BinaryIO, size: int) -> tuple[Container, _Read]:
    magic = _read_exactly(f, 0, 4)
    if magic == _CISO_MAGIC:
        return CONTAINER_CISO, _ciso_reader(f, size)
    if magic is not None and int.from_bytes(magic, "little") == _GCZ_MAGIC:
        return CONTAINER_GCZ, _gcz_reader(f, size)
    if magic == _WBFS_MAGIC:
        return CONTAINER_WBFS, _wbfs_reader(f, size)
    if magic in _WIA_VERSIONS:
        assert magic is not None
        return (CONTAINER_WIA if magic == _WIA_MAGIC else CONTAINER_RVZ), _wia_reader(f, size, magic)
    return CONTAINER_PLAIN, lambda offset, length: _read_exactly(f, offset, length) if offset + length <= size else None


def _ciso_reader(f: BinaryIO, size: int) -> _Read:
    header = _read_exactly(f, 0, _CISO_HEADER_SIZE)
    if header is None:
        raise DolphinDiscUnread("short CISO header")
    block_size = int.from_bytes(header[4:8], "little")
    if block_size == 0:
        raise DolphinDiscUnread("CISO block size 0")
    used = header[8:]

    def piece(block: int, within: int, length: int) -> bytes | None:
        if used[block] != 1:
            return bytes(length)
        stored = _CISO_HEADER_SIZE + used[:block].count(1) * block_size + within
        return _read_exactly(f, stored, length) if stored + length <= size else None

    return _blocked(block_size, _CISO_MAP_SIZE * block_size, piece)


def _blocked(block_size: int, data_size: int, piece: Callable[[int, int, int], "bytes | None"]) -> _Read:
    """A disc read assembled from per-block pieces, refused past *data_size* the way each reader refuses it."""

    def read(offset: int, length: int) -> bytes | None:
        if offset + length > data_size:
            return None
        out = bytearray()
        while length:
            block, within = divmod(offset, block_size)
            take = min(block_size - within, length)
            data = piece(block, within, take)
            if data is None:
                return None
            out += data
            offset += take
            length -= take
        return bytes(out)

    return read


def _gcz_reader(f: BinaryIO, size: int) -> _Read:
    raw = _read_exactly(f, 0, _GCZ_HEADER.size)
    if raw is None:
        raise DolphinDiscUnread("short GCZ header")
    _, _, compressed_size, disc_size, block_size, blocks = _GCZ_HEADER.unpack(raw)
    header_size = _GCZ_HEADER.size + blocks * 12
    if not blocks or not 0 < block_size <= _GCZ_BLOCK_LIMIT or header_size + compressed_size > size:
        raise DolphinDiscUnread("GCZ header out of bounds")

    def pointer(block: int) -> int:
        data = _read_exactly(f, _GCZ_HEADER.size + block * 8, 8)
        assert data is not None  # inside the header, which the file holds
        return int.from_bytes(data, "little")

    def piece(block: int, within: int, length: int) -> bytes | None:
        whole = _gcz_block(f, block, pointer, blocks=blocks, block_size=block_size,
                           compressed_size=compressed_size, data_offset=header_size)
        return None if whole is None else whole[within : within + length]

    return _blocked(block_size, disc_size, piece)


def _gcz_block(
    f: BinaryIO,
    block: int,
    pointer: Callable[[int], int],
    *,
    blocks: int,
    block_size: int,
    compressed_size: int,
    data_offset: int,
) -> bytes | None:
    """One GCZ block as ``GetBlock`` produces it, or ``None`` where Dolphin's read fails."""
    if block >= blocks:
        return None
    start = pointer(block)
    end = pointer(block + 1) & ~_GCZ_UNCOMPRESSED if block < blocks - 1 else compressed_size
    length = end - (start & ~_GCZ_UNCOMPRESSED)
    stored_raw = bool(start & _GCZ_UNCOMPRESSED)
    if length < 0 or length > (block_size if stored_raw else block_size + _GCZ_ZLIB_MARGIN):
        return None
    if stored_raw and length != block_size:
        return None
    data = _read_exactly(f, data_offset + (start & ~_GCZ_UNCOMPRESSED), length)
    if data is None or stored_raw:
        return data
    try:
        inflated = zlib.decompressobj().decompress(data, block_size)
    except zlib.error:
        return None
    return inflated if len(inflated) == block_size else None


def _wbfs_reader(f: BinaryIO, size: int) -> _Read:
    raw = _read_exactly(f, 0, _WBFS_HEADER.size)
    if raw is None:
        raise DolphinDiscUnread("short WBFS header")
    _, hd_sectors, hd_shift, wbfs_shift, first_disc = _WBFS_HEADER.unpack(raw)
    hd_sector, wbfs_sector = 1 << hd_shift, 1 << wbfs_shift
    # A single file holds every HD sector the header counts; a split set's
    # first part holds fewer, and only its later parts are not opened here.
    if wbfs_sector < _WII_SECTOR_SIZE or size > hd_sectors * hd_sector or not first_disc:
        raise DolphinDiscUnread("WBFS header out of bounds")
    clusters = -(-_WII_DISC_SIZE // wbfs_sector)

    def piece(cluster: int, within: int, length: int) -> bytes | None:
        if cluster >= clusters:
            return None
        entry = _read_exactly(f, hd_sector + _WBFS_DISC_HEADER_SIZE + cluster * 2, 2)
        if entry is None:
            return None
        stored = int.from_bytes(entry, "big") * wbfs_sector + within
        return _read_exactly(f, stored, length) if stored + length <= size else None

    return _blocked(wbfs_sector, _WII_DISC_SIZE, piece)


def _wia_reader(f: BinaryIO, size: int, magic: bytes) -> _Read:
    raw = _read_exactly(f, 0, _WIA_HEADER_1.size)
    if raw is None:
        raise DolphinDiscUnread("short WIA header")
    _, version, compatible, header_2_size, header_2_hash, disc_size, file_size, header_1_hash = _WIA_HEADER_1.unpack(
        raw
    )
    supported, read_floor = _WIA_VERSIONS[magic]
    if supported < compatible or read_floor > version:
        raise DolphinDiscUnread("WIA version not read")
    if hashlib.sha1(raw[:_WIA_HEADER_1_HASHED]).digest() != header_1_hash or file_size != size:
        raise DolphinDiscUnread("WIA header 1 does not hold")
    if header_2_size < _WIA_HEADER_2_MINIMUM:
        raise DolphinDiscUnread("WIA header 2 too short")
    header_2 = _read_exactly(f, _WIA_HEADER_1.size, header_2_size)
    if header_2 is None or hashlib.sha1(header_2).digest() != header_2_hash:
        raise DolphinDiscUnread("WIA header 2 does not hold")
    disc_header = header_2[_WIA_DISC_HEADER_OFFSET : _WIA_DISC_HEADER_OFFSET + _WIA_DISC_HEADER_SIZE]
    exposed = min(_WIA_DISC_HEADER_SIZE, disc_size)
    return lambda offset, length: disc_header[offset : offset + length] if offset + length <= exposed else None


def _ticket_title_id(read: _Read) -> int | None:
    """The game partition's ticket's title id, or ``None`` where it is not exposed or no valid ticket is there."""
    partition = _game_partition(read)
    if partition is None:
        return None
    ticket = read(partition, _TICKET_SIZE)
    if ticket is None or _u32(ticket, 0) not in _SIGNATURE_TYPES or ticket[_TICKET_VERSION_OFFSET] != 0:
        return None
    return int.from_bytes(ticket[_TICKET_TITLE_ID_OFFSET : _TICKET_TITLE_ID_OFFSET + 8], "big")


def _game_partition(read: _Read) -> int | None:
    """The first type-0 partition's disc offset, in group order — the walk ``VolumeWii``'s constructor makes."""
    for group in range(_PARTITION_GROUPS):
        entry = read(_PARTITION_TABLE + group * 8, 8)
        if entry is None:
            continue
        count, table = _u32(entry, 0), _u32(entry, 4) << 2
        for index in range(min(count, _PARTITION_LIMIT)):
            row = read(table + index * 8, 8)
            if row is not None and _u32(row, 4) == _GAME_PARTITION_TYPE:
                return _u32(row, 0) << 2
    return None
