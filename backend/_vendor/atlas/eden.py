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
from typing import Final, NamedTuple

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


# ── Where Eden finds a game's updates and add-ons without installing them ──
#
# Eden registers the updates and add-on content it finds in Switch packages
# lying in folders, beside what is installed to its NAND. Two lists of folders
# feed it, both read from ``[Paths]`` of the settings file
# (``QtConfig::ReadPathValues``, ``src/qt_common/config/qt_config.cpp:192-245``):
#
# - ``external_content_dirs``: opened when Eden starts, before a game named on
#   its command line boots (``MainWindow::MainWindow``,
#   ``src/yuzu/main_window.cpp:421`` reads the settings and :553 creates the
#   filesystem factories; ``FileSystemController::CreateFactories``,
#   ``src/core/hle/service/filesystem/filesystem.cpp:725-754``), and scanned
#   then, every subfolder included (``ExternalContentProvider``,
#   ``src/core/file_sys/registered_cache.cpp:1311-1368``).
# - the game folders, ``gamedirs``: scanned for the same packages only where
#   ``[Data%20Storage] ext_content_from_game_dirs`` is on, its default
#   (``settings.h:767-768``; ``GameListWorker::ScanFileSystem``,
#   ``src/yuzu/game/game_list_worker.cpp:341-452``, :383-386), a folder's
#   subfolders only where its ``deep_scan`` is set (:446-451). The scan is the
#   game list's, run on a worker thread (``GameList::PopulateAsync``,
#   ``src/yuzu/game/game_list.cpp:1069-1093``) that Eden starts at :572 and
#   does not wait for before booting the game the command line names (:695-696).

SECTION_PATHS: Final = "Paths"
KEY_GAME_DIRS: Final = "gamedirs"
KEY_EXTERNAL_CONTENT_DIRS: Final = "external_content_dirs"
KEY_EXT_CONTENT_FROM_GAME_DIRS: Final = "ext_content_from_game_dirs"
# The game-list rows that stand for installed content rather than a folder
# (qt_config.cpp:215-224; GameListWorker::run, game_list_worker.cpp:467-479).
VIRTUAL_GAME_DIRS: Final = frozenset({"SDMC", "UserNAND", "SysNAND"})
# The package extensions both scans register extras from: the external scan
# by the lowered extension (registered_cache.cpp:1347-1361), the game-list
# scan by its supported extensions compared case-insensitively
# (game_list.cpp:1116-1118, game_list_worker.cpp:149-152, :353) and then the
# loader's own reading of the file as an XCI or an NSP (:359-386).
EXTRA_CONTENT_EXTENSIONS: Final = (".nsp", ".xci")


class GameDir(NamedTuple):
    """One row of Eden's game list as it reads it: the folder, and whether its subfolders are scanned."""

    path: str
    deep_scan: bool


def simpleini_long(value: str | None, default: int) -> int:
    """``CSimpleIniA::GetLongValue``: decimal, or hex after ``0x``, the whole value — else *default*.

    SimpleIni is not in Eden's tree (it is fetched at build time), so this is
    the library's documented reading rather than one read at Eden's revision.
    """
    if not value:
        return default
    text, base = value, 10
    if len(value) > 1 and value[0] == "0" and value[1] in "xX":
        text, base = value[2:], 16
        if not text:
            return default
    stripped = text.lstrip(" \t\n\v\f\r")
    body = stripped[1:] if stripped[:1] in ("+", "-") else stripped
    digits = "0123456789abcdefABCDEF"[: 10 if base == 10 else 22]
    if not body or any(ch not in digits for ch in body):
        return default
    return int(stripped, base)


def _array_size(values: Mapping[tuple[str, str], str], section: str, array: str) -> int:
    """``Config::BeginArray``: the ``<array>\\size`` long value, 0 where absent (config.cpp:1051-1057)."""
    return simpleini_long(values.get((_lower(section), _lower(f"{array}\\size"))), 0)


def _array_key(array: str, index: int, key: str) -> str:
    """``Config::GetFullKey`` inside an array: ``<array>\\<index + 1>\\<key>`` (config.cpp:1032-1049, :1081-1095)."""
    return f"{array}\\{index + 1}\\{key}"


def read_boolean_setting(
    values: Mapping[tuple[str, str], str], section: str, key: str, default: bool
) -> bool:
    """``Config::ReadBooleanSetting`` with a default: *default* where ``<key>\\default`` is true, else the value.

    config.cpp:717-730 — both reads through ``GetBoolValue``, the companion's
    own default false.
    """
    if simpleini_bool(ini_string(values, section, key + "\\default"), False):
        return default
    return simpleini_bool(ini_string(values, section, key), default)


def game_dirs(values: Mapping[tuple[str, str], str]) -> tuple[GameDir, ...]:
    """Eden's game list as ``QtConfig::ReadPathValues`` builds it (qt_config.cpp:192-227).

    Every row of ``[Paths] gamedirs``, its ``path`` with each ``"`` dropped
    and its ``deep_scan`` read with the default false. With no row at all
    Eden puts its three installed-content rows in and carries an old
    ``gameListRootDir`` over (with ``gameListDeepScan``) where one is set to
    anything but ``.``.
    """
    rows: list[GameDir] = []
    for index in range(_array_size(values, SECTION_PATHS, KEY_GAME_DIRS)):
        path = ini_string(values, SECTION_PATHS, _array_key(KEY_GAME_DIRS, index, "path")) or ""
        deep = read_boolean_setting(values, SECTION_PATHS, _array_key(KEY_GAME_DIRS, index, "deep_scan"), False)
        rows.append(GameDir(path, deep))
    if rows:
        return tuple(rows)
    rows = [GameDir(name, False) for name in ("SDMC", "UserNAND", "SysNAND")]
    # ReadStringSetting with a default: the default where ``\default`` is
    # true (its own default true), else the value with ``"`` dropped and
    # ``//`` made ``/`` (config.cpp:803-825).
    if simpleini_bool(ini_string(values, SECTION_PATHS, "gameListRootDir\\default"), True):
        root = "."
    else:
        raw = values.get((_lower(SECTION_PATHS), _lower("gameListRootDir")))
        root = "." if raw is None else raw.replace('"', "").replace("//", "/")
    if root != ".":
        rows.append(GameDir(root, read_boolean_setting(values, SECTION_PATHS, "gameListDeepScan", False)))
    return tuple(rows)


def external_content_dirs(values: Mapping[tuple[str, str], str]) -> tuple[str, ...]:
    """``[Paths] external_content_dirs``: each row's ``path``, ``"`` dropped, empty rows skipped.

    qt_config.cpp:234-242.
    """
    found: list[str] = []
    for index in range(_array_size(values, SECTION_PATHS, KEY_EXTERNAL_CONTENT_DIRS)):
        path = ini_string(values, SECTION_PATHS, _array_key(KEY_EXTERNAL_CONTENT_DIRS, index, "path"))
        if path:
            found.append(path)
    return tuple(found)


def ext_content_from_game_dirs(values: Mapping[tuple[str, str], str]) -> bool:
    """``[Data%20Storage] ext_content_from_game_dirs`` as Eden loads it, default true.

    A generic setting (``Config::ReadSettingGeneric``, config.cpp:912-937):
    its ``\\default`` companion read through ``ReadBooleanSetting`` with the
    default true; where that is false, the value read as a string with the
    default ``true`` (config.cpp:803-825) and taken as true only where it is
    exactly ``true`` (``Setting::LoadString``, ``settings_setting.h:186-208``)
    — an empty one keeps the default.
    """
    key = KEY_EXT_CONTENT_FROM_GAME_DIRS
    if read_boolean_setting(values, SECTION_DATA_STORAGE, key + "\\default", True):
        return True
    # The companion read false, so the string read takes the value itself.
    raw = values.get((_lower(SECTION_DATA_STORAGE), _lower(key)))
    text = "true" if raw is None else raw.replace('"', "").replace("//", "/")
    return True if not text else text == "true"
