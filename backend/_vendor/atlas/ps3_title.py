"""Read the title id RPCS3 runs a PS3 game under from the game's own bytes — stdlib only, pure.

Every citation is at RPCS3 d5213de6, the build RetroDECK ships and the RPCS3
save card pins (held by ``tests/test_standalone_build_tripwire.py`` against
RetroDECK's deployed binary; EmuDeck's AppImage build is not pinned). A game
saves through ``cellSaveData`` in folders directly below
``dev_hdd0/home/<user>/savedata``, each named by the game itself; the
emulator's own listing for the game takes the folders beginning with the
title id it runs the game under (``Emu.GetTitleID()``,
``rpcs3/Emu/Cell/Modules/cellSaveData.cpp:312-314``, :822-826). That id is
``TITLE_ID`` in the ``PARAM.SFO`` the boot loads (``Emulator::Load``,
``rpcs3/Emu/System.cpp:1713-1745``). This module reads it from one file, in
whichever of three forms the file is, told apart by its own first bytes:

- **a ``PARAM.SFO``** (``\\0PSF``): ``TITLE_ID`` as ``psf::load`` keeps it
  (:func:`atlas.ps3_file.psf_registry`, ``rpcs3/Loader/PSF.cpp:182-284``).
  Which ``PARAM.SFO`` a folder's boot loads is the caller's to find — it
  lies beside the executable's folder, not in the file this module is
  handed.
- **a PSN package** (``\\x7FPKG``): the header is unencrypted
  (``PKGHeader``, ``rpcs3/Crypto/unpkg.h:103-119``). RPCS3 takes a file
  whose magic, release type and platform it knows
  (``package_reader::read_header``, ``rpcs3/Crypto/unpkg.cpp:163-197``) and
  reads the nine bytes at offset 55 as the title id it installs the game
  under — the title part of the content id the header carries from offset
  0x30, ``UP0001-NPUB30000_00-…`` (``read_metadata``, :249-253). A PSP or
  PS Vita package is no PS3 game's. The metadata packets that follow the
  header lie unencrypted too, and two of them decide where an install puts
  the package (:func:`read_facts` reads them): its content type, and an
  install directory that replaces those nine bytes (:257-551).
- **an ISO 9660 image** (``CD001`` at ``0x8001``, ``is_iso_file``,
  ``rpcs3/Loader/ISO.cpp:63-118``): ``PS3_GAME/PARAM.SFO`` in it, the folder
  RPCS3 loads an image's ``PARAM.SFO`` from
  (``rpcs3/Emu/system_utils.cpp:696``), looked up as
  :func:`atlas.ps3_iso.file_bytes` looks a path up. An image whose
  ``PARAM.SFO`` lies in an encrypted region reads as no ``PARAM.SFO``.

A SELF or ELF (``SCE\\0``, ``\\x7fELF``) is an executable whose id lies in a
``PARAM.SFO`` elsewhere (:class:`Ps3TitleExecutable`); anything else is a
file this reader does not take (:class:`Ps3TitleFormatNotRead`).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import BinaryIO, Final, Literal

from .ps3_file import MAGIC_ELF, MAGIC_PSF, MAGIC_SELF, PSF_SIZE_LIMIT, ISO_DESCRIPTORS_OFFSET, psf_registry
from .ps3_iso import file_bytes

Ps3TitleSource = Literal["param-sfo", "pkg", "iso"]
SOURCE_PARAM_SFO: Ps3TitleSource = "param-sfo"
SOURCE_PKG: Ps3TitleSource = "pkg"
SOURCE_ISO: Ps3TitleSource = "iso"
PS3_TITLE_SOURCES: tuple[Ps3TitleSource, ...] = (SOURCE_PARAM_SFO, SOURCE_PKG, SOURCE_ISO)

_PKG_MAGIC: Final = b"\x7fPKG"
# ``PKGHeader`` up to the end of its content id (unpkg.h:103-115): the magic,
# then big-endian type and platform at 4 and 6, the content id at 0x30.
_PKG_HEAD: Final = 0x30 + 48
_PKG_TYPES: Final = (0x8000, 0x0000)  # PKG_RELEASE_TYPE_RELEASE, _DEBUG (unpkg.h:23-24)
_PKG_PLATFORM_PS3: Final = 0x0001  # PKG_PLATFORM_TYPE_PS3 (unpkg.h:26)
_PKG_PLATFORM_PSP_PSVITA: Final = 0x0002  # PKG_PLATFORM_TYPE_PSP_PSVITA (unpkg.h:27)
_PKG_TITLE_ID: Final = slice(55, 55 + 9)
# The metadata's place and count, big-endian at 8 and 12 (PKGHeader, unpkg.h:108-109).
_PKG_META_PLACE: Final = 8
# The packets ``read_metadata`` keeps a value from where this reading needs one:
# the content type, four bytes (:286-299), and an install directory, the text
# after the packet's first eight bytes (:423-436).
_PKG_PACKET_CONTENT_TYPE: Final = 0x2
_PKG_PACKET_INSTALL_DIR: Final = 0xA
# Bounds on the metadata this reading walks: more packets, or packets reaching
# further, leave the metadata unread rather than read in part.
PKG_META_PACKETS_LIMIT: Final = 64
PKG_META_BYTES_LIMIT: Final = 1 << 16
_ISO_IDENTIFIER: Final = b"CD001"
_ISO_SFO: Final = ("PS3_GAME", "PARAM.SFO")
_TITLE_ID_KEY: Final = b"TITLE_ID"

# The shape of a PS3 product code: four letters, five digits (BLUS30443,
# NPUB30058). The savedata utility does not require it of a folder name, but
# an id of another shape names no prefix this reader stands behind.
_TITLE_ID = re.compile(r"[A-Z]{4}[0-9]{5}")


class Ps3TitleUnread(Exception):
    """A file of a form this reader takes that yields no title id — a ``PARAM.SFO`` the loader clears or that
    states none, a package RPCS3 refuses, an image without ``PS3_GAME/PARAM.SFO``."""


class Ps3TitleFormatNotRead(Exception):
    """A file that is none of the three forms — or a PSP or PS Vita package, which names no PS3 game."""


class Ps3TitleExecutable(Exception):
    """A SELF or ELF: RPCS3 boots it and takes the title id from the ``PARAM.SFO`` beside its folder."""


@dataclass(frozen=True, slots=True)
class Ps3TitleFacts:
    """Where a title id was read from, and the id as the file states it.

    A package also carries what its metadata says about where RPCS3 installs
    it: ``content_type`` the value of its content-type packet, ``0`` where it
    has none (``PKGMetaData``'s default, unpkg.h:171), and ``None`` where the
    metadata was not read; ``install_dir`` the directory an install-directory
    packet names in place of the header's nine bytes, ``None`` where there is
    none or the metadata was not read. Both are ``None`` on every other source.
    """

    source: Ps3TitleSource
    title_id: str
    content_type: int | None = None
    install_dir: str | None = None

    def __post_init__(self) -> None:
        if self.source not in PS3_TITLE_SOURCES:
            raise ValueError(f"Ps3TitleFacts: source must be one of {PS3_TITLE_SOURCES}, got {self.source!r}")
        if not self.title_id or "\0" in self.title_id:
            raise ValueError("Ps3TitleFacts: title_id is the non-empty string the file states")
        if self.source != SOURCE_PKG and (self.content_type is not None or self.install_dir is not None):
            raise ValueError("Ps3TitleFacts: content_type and install_dir are a package's alone")
        if self.content_type is None and self.install_dir is not None:
            raise ValueError("Ps3TitleFacts: an install_dir is read from metadata whose content type was read too")
        if self.content_type is not None and not 0 <= self.content_type <= 0xFFFFFFFF:
            raise ValueError("Ps3TitleFacts: content_type is an unsigned 32-bit value")


def title_id(facts: Ps3TitleFacts) -> str | None:
    """The nine-character product code the facts name — ``None`` where the id is of another shape.

    Compared exactly, as ``starts_with`` compares a folder name with it
    (cellSaveData.cpp:245): a lowercase or dashed spelling is not the id the
    game runs under.
    """
    return facts.title_id if _TITLE_ID.fullmatch(facts.title_id) else None


def read_facts(handle: BinaryIO, size: int) -> Ps3TitleFacts:
    """The title id of the file *handle* reads, *size* bytes long — every read bounded by it.

    Raises :class:`Ps3TitleExecutable` for a SELF or ELF,
    :class:`Ps3TitleFormatNotRead` for a file of no form this reader takes,
    and :class:`Ps3TitleUnread` for one of a taken form that names no id.
    """
    handle.seek(0)
    head = handle.read(_PKG_HEAD)
    magic = head[:4]
    if magic == _PKG_MAGIC:
        title = _pkg_title_id(head)
        metadata = _pkg_metadata(handle, size, head)
        if metadata is None:
            return Ps3TitleFacts(SOURCE_PKG, title)
        return Ps3TitleFacts(SOURCE_PKG, title, *metadata)
    if magic == MAGIC_PSF.encode("latin-1"):
        return Ps3TitleFacts(SOURCE_PARAM_SFO, _sfo_title_id(_whole(handle, size)))
    if magic in (MAGIC_SELF.encode("latin-1"), MAGIC_ELF.encode("latin-1")):
        raise Ps3TitleExecutable("a SELF or ELF, whose title id is its folder's PARAM.SFO's")
    if size >= ISO_DESCRIPTORS_OFFSET + 6:
        handle.seek(ISO_DESCRIPTORS_OFFSET + 1)
        if handle.read(len(_ISO_IDENTIFIER)) == _ISO_IDENTIFIER:
            sfo = file_bytes(handle, size, _ISO_SFO, PSF_SIZE_LIMIT)
            if sfo is None:
                raise Ps3TitleUnread("an ISO 9660 image without a PS3_GAME/PARAM.SFO this reading reaches")
            return Ps3TitleFacts(SOURCE_ISO, _sfo_title_id(sfo))
    raise Ps3TitleFormatNotRead("no PARAM.SFO, PSN package, ISO 9660 image or executable")


def _whole(handle: BinaryIO, size: int) -> bytes:
    if size > PSF_SIZE_LIMIT:
        raise Ps3TitleUnread(f"a PARAM.SFO of {size} bytes is beyond the {PSF_SIZE_LIMIT} atlas reads")
    handle.seek(0)
    return handle.read(size)


def _sfo_title_id(data: bytes) -> str:
    """``TITLE_ID`` as ``psf::get_string`` answers it from what ``psf::load`` keeps — or :class:`Ps3TitleUnread`."""
    registry = psf_registry(data)
    if registry is None:
        raise Ps3TitleUnread("a PARAM.SFO RPCS3's loader keeps nothing of")
    value = registry.get(_TITLE_ID_KEY)
    if not value:
        raise Ps3TitleUnread("a PARAM.SFO stating no TITLE_ID string")
    return value.decode("latin-1")


def _pkg_title_id(head: bytes) -> str:
    """The title id ``read_metadata`` installs a package under — after the header checks ``read_header`` makes."""
    if len(head) < _PKG_HEAD:
        raise Ps3TitleUnread("a package shorter than its header")
    pkg_type, platform = struct.unpack_from(">HH", head, 4)
    if pkg_type not in _PKG_TYPES:
        raise Ps3TitleUnread(f"a package of release type {pkg_type:#06x}, which RPCS3 refuses")
    if platform == _PKG_PLATFORM_PSP_PSVITA:
        raise Ps3TitleFormatNotRead("a PSP or PS Vita package")
    if platform != _PKG_PLATFORM_PS3:
        raise Ps3TitleUnread(f"a package of platform {platform:#06x}, which RPCS3 refuses")
    raw = head[_PKG_TITLE_ID].split(b"\0", 1)[0]
    if not raw:
        raise Ps3TitleUnread("a package whose content id names no title")
    return raw.decode("latin-1")


def _pkg_metadata(handle: BinaryIO, size: int, head: bytes) -> tuple[int, str | None] | None:
    """The content type and install directory ``read_metadata`` keeps — ``None`` where the metadata is not read.

    The walk is RPCS3's (unpkg.cpp:257-551): ``meta_count`` packets from
    ``meta_offset``, each an eight-byte id and size and then its data; a
    content-type packet four bytes long sets the type, an install-directory
    packet longer than eight bytes sets the directory to its text after those
    eight, up to the first NUL (``c_str() + 8``), and a later packet of either
    replaces an earlier one. Every other packet, and one of either whose size
    RPCS3 refuses, is passed over. A walk beyond the file's end, or beyond
    :data:`PKG_META_PACKETS_LIMIT` packets or :data:`PKG_META_BYTES_LIMIT`
    bytes, is not read: RPCS3 would read on into what is not there.
    """
    offset, count = struct.unpack_from(">II", head, _PKG_META_PLACE)
    if count > PKG_META_PACKETS_LIMIT:
        return None
    content_type = 0
    install_dir: str | None = None
    position = offset
    for _ in range(count):
        if position + 8 > size or position + 8 - offset > PKG_META_BYTES_LIMIT:
            return None
        handle.seek(position)
        packet_id, packet_size = struct.unpack(">II", handle.read(8))
        end = position + 8 + packet_size
        if end > size or end - offset > PKG_META_BYTES_LIMIT:
            return None
        if packet_id == _PKG_PACKET_CONTENT_TYPE and packet_size == 4:
            content_type = struct.unpack(">I", handle.read(4))[0]
        elif packet_id == _PKG_PACKET_INSTALL_DIR and packet_size > 8:
            data = handle.read(packet_size)
            install_dir = data[8:].split(b"\0", 1)[0].decode("latin-1")
        position = end
    return content_type, install_dir
