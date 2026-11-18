"""Read what Azahar reads of a 3DS image to key its saves — stdlib only, pure.

Azahar keeps a title's save on the emulated SD at
``Nintendo 3DS/<ID0>/<ID1>/title/<high:08x>/<low:08x>/data/00000001/``, the
two words those of the program id the emulator runs the title under
(``GetSaveDataPath``, ``src/core/file_sys/archive_source_sd_savedata.cpp:25-29``
— azahar-emu/azahar 2126.1.1), with the archive's format record beside it as
``data/00000001.metadata`` (:31-35). Its extra data lives under
``Nintendo 3DS/<ID0>/<ID1>/extdata/<high:08X>/<low:08X>/`` — uppercase hex,
the words those of the extdata id the game opens
(``GetExtSaveDataPath``, ``archive_extsavedata.cpp:183-190``, and
``GetExtDataContainerPath`` :192-197). This module performs the one read that
establishes the two ids from an image's bytes, and nothing past it.

**The image.** Azahar opens a file as a 3DS image when the four bytes at
``0x100`` say ``NCSD`` or ``NCCH`` (``AutoOpenNCCHNCSD``,
``src/core/file_sys/ncch_container.cpp:120-133``); anything else is its own
console-encrypted file, a compressed Z3DS image (:138-162), or a CIA, which
another loader installs. Only the first two are read here; the rest are
:class:`N3dsRomFormatNotRead`. An ``NCSD`` image (a ``.3ds`` / ``.cci`` card
dump) holds its program as partition 0, at the offset its partition table
states in 0x200-byte units (``LoadHeader``, :187-233; ``NCSD_Header``,
``ncch_container.h:25-41``); an ``NCCH`` (a ``.cxi``) is the program itself.

**The program id.** ``ReadProgramId`` answers the NCCH header's ``program_id``
(``ncch_container.cpp:680-689``; the u64 at ``0x118``, ``ncch_container.h:43-100``),
and the loader creates the title's process under it (``LoadExec``,
``src/core/loader/ncch.cpp:122-140``) — the id the save path is keyed by. An
NCCH whose ``no_crypto`` flag is clear is refused (``LoadHeader``,
``ncch_container.cpp:226-229``: "Encrypted NCCH are not supported"), so such an
image is :class:`N3dsRomEncrypted` rather than a title read.

**The extdata id.** A game names the extdata it opens in its own request; the
id it is granted is in its extended header, which follows the NCCH header
(``Load``, :264-275). Azahar's own answer to "which extdata is this title's"
is ``ReadExtdataId`` (:692-722), and this reader answers the same: the storage
info's ``ext_save_data_id`` (``ExHeader_StorageInfo``, ``ncch_container.h:147-167``,
at extended header ``0x230``), or — where the title uses extended savedata
access (``other_attributes >> 1``) — the first non-zero of the six 20-bit ids
packed into ``storage_accessible_unique_ids`` and ``ext_save_data_id``, which
Azahar itself calls a guess. A title with no extended header, or whose id is
zero, names none.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Final, Literal

MEDIA_UNIT: Final = 0x200
_MAGIC_AT: Final = 0x100
_NCSD_MAGIC: Final = b"NCSD"
_NCCH_MAGIC: Final = b"NCCH"
# NCSD_Header: partitions[0] = {offset, size} in media units.
_NCSD_PARTITION0: Final = 0x120
# NCCH_Header fields this reader takes.
_NCCH_CONTENT_SIZE: Final = 0x104
_NCCH_PROGRAM_ID: Final = 0x118
_NCCH_EXHEADER_SIZE: Final = 0x180
_NCCH_FLAGS7: Final = 0x18F
_NO_CRYPTO: Final = 0x04
_NCCH_HEADER_SIZE: Final = 0x200
# ExHeader_Header: arm11_system_local_caps begins at 0x200, its storage info at +0x30.
_STORAGE_INFO: Final = 0x230
_STORAGE_INFO_SIZE: Final = 0x20
# The bytes one read takes at the program: its header and the extended header up
# to the end of the storage info.
_PROGRAM_READ: Final = _NCCH_HEADER_SIZE + _STORAGE_INFO + _STORAGE_INFO_SIZE

N3dsContainer = Literal["ncsd", "ncch"]
CONTAINER_NCSD: N3dsContainer = "ncsd"
CONTAINER_NCCH: N3dsContainer = "ncch"
CONTAINERS: tuple[N3dsContainer, ...] = (CONTAINER_NCSD, CONTAINER_NCCH)

# How the extdata id was taken from the extended header: the plain
# ext_save_data_id, or the first non-zero id under extended savedata access.
ExtdataBasis = Literal["exheader-id", "extended-access-first"]
EXTDATA_EXHEADER_ID: ExtdataBasis = "exheader-id"
EXTDATA_EXTENDED_FIRST: ExtdataBasis = "extended-access-first"
EXTDATA_BASES: tuple[ExtdataBasis, ...] = (EXTDATA_EXHEADER_ID, EXTDATA_EXTENDED_FIRST)

_U64_MAX: Final = (1 << 64) - 1
_ID20: Final = (1 << 20) - 1


class N3dsRomUnread(Exception):
    """An image Azahar opens as NCSD or NCCH whose structure this reader cannot follow."""


class N3dsRomFormatNotRead(Exception):
    """A file that is no plain NCSD or NCCH image — a CIA, a Z3DS image, Azahar's encrypted file, or none."""


class N3dsRomEncrypted(Exception):
    """An NCCH whose ``no_crypto`` flag is clear — one Azahar refuses to load."""


@dataclass(frozen=True, slots=True)
class N3dsRomFacts:
    """What Azahar keys a title's saves by: its program id and the extdata id it is granted.

    ``extdata_id`` is ``None`` where the image names none — no extended
    header, or an id of zero — and ``extdata_basis`` is ``None`` exactly then.
    """

    container: N3dsContainer
    program_id: int
    extdata_id: int | None
    extdata_basis: ExtdataBasis | None

    def __post_init__(self) -> None:
        if self.container not in CONTAINERS:
            raise ValueError(f"N3dsRomFacts: container must be one of {CONTAINERS}, got {self.container!r}")
        for name, value in (("program_id", self.program_id), ("extdata_id", self.extdata_id)):
            if value is None and name == "extdata_id":
                continue
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= _U64_MAX:
                raise ValueError(f"N3dsRomFacts: {name} is a u64, got {value!r}")
        if self.extdata_id == 0:
            raise ValueError("N3dsRomFacts: an extdata id of zero names none — state it as None")
        if (self.extdata_id is None) != (self.extdata_basis is None):
            raise ValueError("N3dsRomFacts: extdata_basis is stated exactly when extdata_id is")
        if self.extdata_basis is not None and self.extdata_basis not in EXTDATA_BASES:
            raise ValueError(f"N3dsRomFacts: extdata_basis must be one of {EXTDATA_BASES}, got {self.extdata_basis!r}")


def title_words(program_id: int) -> tuple[str, str]:
    """The program id as the save path's two segments: high and low word, 8 lowercase hex each."""
    return f"{program_id >> 32:08x}", f"{program_id & 0xFFFFFFFF:08x}"


def extdata_words(extdata_id: int) -> tuple[str, str]:
    """The extdata id as the extdata path's two segments: high and low word, 8 UPPERCASE hex each."""
    return f"{extdata_id >> 32:08X}", f"{extdata_id & 0xFFFFFFFF:08X}"


def read_facts(f: BinaryIO, size: int) -> N3dsRomFacts:
    """Read the program id and extdata id from the image open as *f*, *size* bytes long.

    Raises :class:`N3dsRomFormatNotRead` where the bytes at ``0x100`` are no
    ``NCSD`` or ``NCCH``, :class:`N3dsRomEncrypted` for an encrypted NCCH and
    :class:`N3dsRomUnread` for an image whose structure runs short or does not
    lead to an NCCH. At most two short reads are taken.
    """
    head = _read_at(f, 0, _PROGRAM_READ)
    magic = head[_MAGIC_AT : _MAGIC_AT + 4]
    if magic == _NCCH_MAGIC:
        return _program(head, CONTAINER_NCCH, size)
    if magic != _NCSD_MAGIC:
        raise N3dsRomFormatNotRead(f"no NCSD or NCCH magic at 0x100 (found {magic!r})")
    if len(head) < _NCSD_PARTITION0 + 8:
        raise N3dsRomUnread("an NCSD header shorter than its partition table")
    offset, length = struct.unpack_from("<II", head, _NCSD_PARTITION0)
    if offset == 0 or length == 0:
        raise N3dsRomUnread("partition 0 is empty")
    start = offset * MEDIA_UNIT
    if start >= size:
        raise N3dsRomUnread("partition 0 starts past the end of the image")
    program = _read_at(f, start, _PROGRAM_READ)
    if program[_MAGIC_AT : _MAGIC_AT + 4] != _NCCH_MAGIC:
        raise N3dsRomUnread("partition 0 holds no NCCH")
    return _program(program, CONTAINER_NCSD, length * MEDIA_UNIT)


def _read_at(f: BinaryIO, offset: int, count: int) -> bytes:
    f.seek(offset)
    return f.read(count)


def _program(data: bytes, container: N3dsContainer, ncch_size: int) -> N3dsRomFacts:
    """The facts of the NCCH whose first bytes are *data*, in a container of *ncch_size* bytes."""
    if len(data) < _NCCH_HEADER_SIZE:
        raise N3dsRomUnread("an NCCH header runs past the end")
    if not data[_NCCH_FLAGS7] & _NO_CRYPTO:
        raise N3dsRomEncrypted("the NCCH is encrypted (no_crypto clear)")
    (program_id,) = struct.unpack_from("<Q", data, _NCCH_PROGRAM_ID)
    (content_size,) = struct.unpack_from("<I", data, _NCCH_CONTENT_SIZE)
    (exheader_size,) = struct.unpack_from("<I", data, _NCCH_EXHEADER_SIZE)
    # A prototype NCCH states its size in bytes and always carries the
    # extended header (Load, ncch_container.cpp:251-255, :264).
    if exheader_size == 0 and content_size != ncch_size:
        return N3dsRomFacts(container, program_id, None, None)
    if len(data) < _PROGRAM_READ:
        raise N3dsRomUnread("the extended header runs past the end")
    extdata_id, basis = _extdata(data[_NCCH_HEADER_SIZE + _STORAGE_INFO : _PROGRAM_READ])
    return N3dsRomFacts(container, program_id, extdata_id, basis)


def _extdata(storage: bytes) -> tuple[int | None, ExtdataBasis | None]:
    """``ReadExtdataId``'s answer from the 0x20 bytes of storage info."""
    ext_save_data_id, _system, accessible = struct.unpack_from("<QQQ", storage, 0)
    other_attributes = storage[_STORAGE_INFO_SIZE - 1]
    if other_attributes >> 1:
        packed = (accessible, ext_save_data_id)
        for word in packed:
            for shift in (40, 20, 0):
                candidate = (word >> shift) & _ID20
                if candidate:
                    return candidate, EXTDATA_EXTENDED_FIRST
        return None, None
    if ext_save_data_id == 0:
        return None, None
    return ext_save_data_id, EXTDATA_EXHEADER_ID
