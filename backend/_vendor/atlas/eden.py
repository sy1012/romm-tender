"""What Eden reads to place a Switch game's save — the pure half: its settings file and its user list.

Eden (eden-emu/eden, a yuzu descendant) keeps every game's save below its NAND
and keys it by the user profile the game runs as. Two of the files it reads to
get there are parsed here, text or bytes in and facts out, so both the real
machine and a fixture reach them; where the files are, and what the facts
place, is :mod:`atlas.installations`' (:class:`~atlas.installations.EdenAppImage`).
Every citation is eden-emu/eden at the v0.2.1 release (58c1e20e), the build
:data:`EDEN_BUILD` names.

**The settings file** is ``qt-config.ini`` in the config directory
(``QtConfig``'s default ``config_name``, ``src/qt_common/config/qt_config.h:15``;
``Config::Initialize`` joins ``<name>.ini`` onto ``ConfigDir``,
``src/frontend_common/config.cpp:29-40``). It is read through ``CSimpleIniA``
(``config.h:221``, ``SetUpIni`` at ``config.cpp:98-123``), whose sections and
keys compare ASCII case-insensitively, and whose last spelling of a key wins.
A category's section is its name with ``/`` turned into ``\\`` and a space into
``%20`` (``Config::AdjustKey``, ``config.cpp:999-1004``), so the data-storage
settings live under ``[Data%20Storage]`` and the user index under ``[System]``
(``Settings::TranslateCategory``, ``src/common/settings.cpp:247-251``).
Every ``"`` is dropped from a string read (``ReadStringSetting``,
``config.cpp:803-825``).

**The user list** is ``profiles.dat`` (``ProfileManager::ParseUserSaveFile``,
``src/core/hle/service/acc/profile_manager.cpp:396-431``): 0x10 bytes of
padding, then eight 0xC8-byte records (``ProfileDataRaw``/``UserRaw``,
:30-44; ``MAX_USERS`` is 8, ``profile_manager.h:20``) whose first sixteen bytes
are the user's UUID. A record whose UUID is all zeros holds no user and is
skipped, and the users kept close up in file order (:417-430), which is the
order the ``current_user`` index counts in. A file shorter than the structure
is read as no file at all (:408-412).
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from typing import Final

EDEN_BUILD: Final = "eden-emu/eden v0.2.1 (58c1e20e)"

# Eden's own directory names (src/common/fs/fs_paths.h:11-12, :17, :23).
EDEN_DIR: Final = "eden"
PORTABLE_DIR: Final = "user"
NAND_DIR: Final = "nand"
CONFIG_DIR: Final = "config"
CONFIG_FILE: Final = "qt-config.ini"

SECTION_DATA_STORAGE: Final = "Data%20Storage"
SECTION_SYSTEM: Final = "System"
KEY_NAND_DIRECTORY: Final = "nand_directory"
KEY_SAVE_DIRECTORY: Final = "save_directory"
KEY_CURRENT_USER: Final = "current_user"

# Where the user list sits below the NAND (ACC_SAVE_AVATORS_BASE_PATH,
# profile_manager.cpp:51, and the file name at :397-398).
PROFILES_FILE: Final = ("system", "save", "8000000000000010", "su", "avators", "profiles.dat")
# Where a user's game saves sit below the save directory: the User save-data
# space (``GetSaveDataSpaceIdPath``, savedata_factory.cpp:93-106) and the
# account save's path, ``save/{:016X}/{:016X}{:016X}/{:016X}`` with a zero
# save id, the user id's high then low word, and the title id (:131-138).
USER_SAVE_TREE: Final = ("user", "save", "0000000000000000")
# The layout Eden prefers where it already exists: ``/user/save/account/<uuid
# raw>/<title id with its low byte cleared>/0`` (``GetFutureSaveDataPath``,
# savedata_factory.cpp:25-53, preferred at :117-126).
FUTURE_ACCOUNT_TREE: Final = ("user", "save", "account")

MAX_USERS: Final = 8
_PROFILES_PADDING: Final = 0x10
_USER_RECORD: Final = 0xC8
PROFILES_SIZE: Final = _PROFILES_PADDING + MAX_USERS * _USER_RECORD
_UUID_SIZE: Final = 0x10
# The system profile's folder, which Eden counts as a user folder no profile
# names (``FindGoodProfiles``' exception list, profile_manager.cpp:525-527).
SYSTEM_USER_FOLDER: Final = "0" * 32


class ProfilesUnread(Exception):
    """``profiles.dat`` is shorter than the structure Eden reads — Eden starts as with no file."""


def parse_profiles(data: bytes) -> tuple[bytes, ...]:
    """The UUIDs of the users ``profiles.dat`` lists, in the order Eden counts them.

    Raises :class:`ProfilesUnread` for a file shorter than the structure.
    """
    if len(data) < PROFILES_SIZE:
        raise ProfilesUnread("shorter than ProfileDataRaw")
    users: list[bytes] = []
    for index in range(MAX_USERS):
        start = _PROFILES_PADDING + index * _USER_RECORD
        uuid = data[start : start + _UUID_SIZE]
        if any(uuid):
            users.append(uuid)
    return tuple(users)


def user_folder(uuid: bytes) -> str:
    """The folder a user's saves sit under: ``{:016X}{:016X}`` of the user id's high, then low, word.

    The id is the UUID's sixteen bytes copied into two little-endian ``u64``s
    (``UUID::AsU128``, ``src/common/uuid.cpp:175-179``), printed high word
    first (savedata_factory.cpp:136-137; ``FindExistingProfileStrings``,
    profile_manager.cpp:503-514, spells the same name).
    """
    low, high = struct.unpack("<QQ", uuid)
    return f"{high:016X}{low:016X}"


def uuid_raw(uuid: bytes) -> str:
    """``UUID::RawString``: the sixteen bytes in order, lowercase (src/common/uuid.cpp:148-154)."""
    return uuid.hex()


def ini_values(text: str) -> dict[tuple[str, str], str]:
    """The settings file as ``(section, key) -> value``, matched the way ``CSimpleIniA`` matches.

    Section and key are lowered ASCII-only, a later key replaces an earlier
    one, and section names are taken as written — ``Data%20Storage`` is that
    literal name, which is the one Eden asks for.
    """
    parsed: dict[tuple[str, str], str] = {}
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = _lower(line[1:-1].strip())
            continue
        key, separator, value = line.partition("=")
        if separator:
            parsed[(section, _lower(key.strip()))] = value.strip()
    return parsed


def _lower(text: str) -> str:
    return "".join(chr(ord(ch) + 32) if "A" <= ch <= "Z" else ch for ch in text)


def ini_string(values: Mapping[tuple[str, str], str], section: str, key: str) -> str | None:
    """A string setting read with no default: the value with every ``"`` dropped, ``None`` where absent."""
    value = values.get((_lower(section), _lower(key)))
    return None if value is None else value.replace('"', "")


def simpleini_bool(value: str | None, default: bool) -> bool:
    """``CSimpleIniA::GetBoolValue``: the first character decides, ``on``/``off`` by the second, else *default*."""
    if not value:
        return default
    first = value[0].lower()
    if first in "ty1":
        return True
    if first in "fn0":
        return False
    if first == "o" and len(value) > 1:
        second = value[1].lower()
        if second == "n":
            return True
        if second == "f":
            return False
    return default


def current_user_index(values: Mapping[tuple[str, str], str]) -> int:
    """The ``[System] current_user`` index Eden loads, before it is clamped to the users there are.

    A generic setting is read only where its ``\\default`` companion is false
    (``Config::ReadSettingGeneric``, config.cpp:912-937, through
    ``ReadBooleanSetting``, :717-730), and its text is then parsed the way
    ``std::stoll`` parses it — leading blanks, a sign, the digits — with the
    default 0 where no digit leads (``Setting::LoadString``,
    ``src/common/settings_setting.h:186-207``). The setting is
    ``Setting<s32> current_user{linkage, 0, …}`` (``settings.h:672``).
    """
    is_default = simpleini_bool(ini_string(values, SECTION_SYSTEM, KEY_CURRENT_USER + "\\default"), True)
    if is_default:
        return 0
    raw = ini_string(values, SECTION_SYSTEM, KEY_CURRENT_USER)
    if raw is None:
        return 0
    raw = raw.replace("//", "/").lstrip(" \t\n\v\f\r")
    sign = ""
    if raw[:1] in ("+", "-"):
        sign, raw = raw[:1], raw[1:]
    digits = ""
    for ch in raw:
        if not ch.isascii() or not ch.isdigit():
            break
        digits += ch
    if not digits:
        return 0
    value = int(sign + digits)
    # stoll out of range keeps the default; an s32 wraps what fits in 64 bits.
    if not -(2**63) <= value < 2**63:
        return 0
    return ((value + 2**31) % 2**32) - 2**31


def active_user_slot(index: int, user_count: int) -> int | None:
    """The slot Eden opens: the index clamped to ``0..7``, and 0 where no user holds it — ``None`` with no user.

    ``ProfileManager::ProfileManager``, profile_manager.cpp:53-72.
    """
    if user_count == 0:
        return None
    current = min(max(index, 0), MAX_USERS - 1)
    return current if current < user_count else 0
