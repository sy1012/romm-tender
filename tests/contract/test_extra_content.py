"""Contract tests for a game's extra content: the offer, a download that brings it, and its removal.

Driven frontend-shaped per ``frontend/src/api/backend.ts``:
``getExtraContent = endpoint<[number], ExtraContentAnswer | EndpointFailure>``,
``startDownload`` with its seventh argument, the ticked file ids,
``downloadExtraContent = endpoint<[number, number[]], BackendResult>`` and
``removeExtraContent = endpoint<[number, number[]], RemoveExtraContentResult>``.

The real resolver answers the not-offered case over the seeded RetroDECK. The
offered case needs an Eden whose settings the resolver reads; the resolver's
own reading of one is ``tests/adapters/test_extra_content_vectors.py``'s, so
here the offer's reader is handed the reading such an Eden gives.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from fakes.fake_extra_content_reader import FakeExtraContentReader

from domain.extra_content import ExtraContentFolders
from domain.rom_install import RomInstall

from ._seed import seed_rom

pytestmark = pytest.mark.usefixtures("seeded_retrodeck")

_FILE_KEYS = {"file_id", "file_name", "rel_path", "category", "size_bytes", "on_device", "ticked", "read_from_folders"}
_ANSWER_KEYS = {"success", "offered", "installed", "files", "game_folder_scanned", "rom_folder"}


async def _drain_background_tasks() -> None:
    for _ in range(6):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _file(file_id: int, rel_path: str, category: str, size: int) -> dict[str, Any]:
    folder, _, name = rel_path.rpartition("/")
    return {
        "id": file_id,
        "file_name": name,
        "file_path": f"gba/Game/{folder}".rstrip("/"),
        "file_size_bytes": size,
        "category": category,
    }


def _seed_server_game(harness, rom_id: int = 1) -> None:
    files = [
        _file(11, "Game.gba", "game", 8),
        _file(12, "update/Game [v65536].nsp", "update", 6),
        _file(13, "update/Game [v131072].nsp", "update", 6),
        _file(14, "dlc/Game DLC.nsp", "dlc", 3),
    ]
    harness.romm.roms[rom_id] = {
        "id": rom_id,
        "name": "Game",
        "fs_name": "Game",
        "fs_name_no_ext": "Game",
        "full_path": "gba/Game",
        "fs_size_bytes": 23,
        "platform_slug": "gba",
        "platform_fs_slug": "gba",
        "platform_name": "GBA",
        "has_simple_single_file": False,
        "has_nested_single_file": False,
        "has_multiple_files": True,
        "files": files,
    }
    for entry in files:
        harness.romm.download_payloads[f"rom:{rom_id}:{entry['file_name']}?file_ids={entry['id']}"] = (
            f"bytes-{entry['id']}".encode()
        )


def _offered(harness) -> FakeExtraContentReader:
    reader = FakeExtraContentReader(
        ExtraContentFolders(offered=True, game_folder_scanned=True, extensions=(".nsp", ".xci"))
    )
    harness.app.services.download_service._extra_content_offer._extra_content = reader  # pyright: ignore[reportPrivateUsage]
    return reader


def _seed_folder_install(harness, rom_id: int = 1) -> str:
    seed_rom(harness, rom_id, platform_slug="gba")
    game_dir = os.path.join(harness.roms_root, "gba", "Game")
    os.makedirs(game_dir, exist_ok=True)
    with open(os.path.join(game_dir, "Game.gba"), "wb") as f:
        f.write(b"base")
    with harness.uow_factory() as uow:
        uow.rom_installs.save(
            RomInstall.mark_installed(
                rom_id=rom_id,
                file_path=os.path.join(game_dir, "Game.gba"),
                rom_dir=game_dir,
                platform_slug="gba",
                system="gba",
                installed_at="2026-11-17T00:00:00",
            )
        )
    return game_dir


# ── get_extra_content ────────────────────────────────────────────────────


async def test_a_game_whose_emulator_states_nothing_is_offered_nothing_and_romm_is_not_asked(harness):
    seed_rom(harness, 1, platform_slug="gba")
    _seed_server_game(harness)

    answer = await harness.endpoints.get_extra_content(1)

    assert answer == {
        "success": True,
        "offered": False,
        "installed": False,
        "files": [],
        "game_folder_scanned": None,
        "rom_folder": None,
    }
    assert not [call for call in harness.romm.call_log if call[0] == "get_rom"]


async def test_an_offered_game_lists_its_files_in_the_answer_s_shape(harness):
    seed_rom(harness, 1, platform_slug="gba")
    _seed_server_game(harness)
    _offered(harness)

    answer = await harness.endpoints.get_extra_content(1)

    assert set(answer) == _ANSWER_KEYS
    assert answer["offered"] is True
    assert answer["rom_folder"] == os.path.join(harness.roms_root, "gba")
    assert all(set(row) == _FILE_KEYS for row in answer["files"])
    assert [(row["file_id"], row["ticked"]) for row in answer["files"]] == [(12, False), (13, True), (14, True)]


async def test_a_game_tender_does_not_know_is_the_canonical_failure(harness):
    assert await harness.endpoints.get_extra_content(404) == {
        "success": False,
        "reason": "not_found",
        "message": "ROM 404 is not in the library",
    }


# ── start_download with ticked extra content ─────────────────────────────


async def test_a_download_brings_the_ticked_extra_content_into_the_game_s_folder(harness):
    seed_rom(harness, 1, platform_slug="gba")
    _seed_server_game(harness)

    result = await harness.endpoints.start_download(1, False, None, None, False, None, [13, 14])
    await _drain_background_tasks()

    assert result == {"success": True, "message": "Download started"}
    with harness.uow_factory() as uow:
        install = uow.rom_installs.get(1)
    assert install is not None
    assert install.rom_dir is not None
    assert sorted((e.file_id, e.rel_path) for e in install.extra_content) == [
        (13, "update/Game [v131072].nsp"),
        (14, "dlc/Game DLC.nsp"),
    ]
    with open(os.path.join(install.rom_dir, "dlc", "Game DLC.nsp"), "rb") as f:
        assert f.read() == b"bytes-14"
    assert not os.path.exists(os.path.join(install.rom_dir, "update", "Game [v65536].nsp"))


async def test_a_download_naming_a_file_that_is_no_extra_content_is_refused(harness):
    seed_rom(harness, 1, platform_slug="gba")
    _seed_server_game(harness)

    result = await harness.endpoints.start_download(1, False, None, None, False, None, [11])

    assert result == {
        "success": False,
        "reason": "unknown_extra_content",
        "message": "RomM holds no update or DLC file of this game with that id",
        "file_ids": [11],
    }


# ── download_extra_content / remove_extra_content ────────────────────────


async def test_extra_content_comes_down_for_an_installed_game_and_is_then_on_the_device(harness):
    game_dir = _seed_folder_install(harness)
    _seed_server_game(harness)
    _offered(harness)

    result = await harness.endpoints.download_extra_content(1, [12])
    await _drain_background_tasks()

    assert result == {"success": True, "message": "Download started"}
    with open(os.path.join(game_dir, "update", "Game [v65536].nsp"), "rb") as f:
        assert f.read() == b"bytes-12"
    answer = await harness.endpoints.get_extra_content(1)
    assert {row["file_id"]: row["on_device"] for row in answer["files"]} == {12: True, 13: False, 14: False}


async def test_extra_content_for_a_game_that_is_not_installed_is_refused(harness):
    seed_rom(harness, 1, platform_slug="gba")
    _seed_server_game(harness)

    result = await harness.endpoints.download_extra_content(1, [12])

    assert result == {"success": False, "reason": "not_installed", "message": "ROM not installed"}


async def test_removed_extra_content_leaves_the_game_installed(harness):
    game_dir = _seed_folder_install(harness)
    _seed_server_game(harness)
    await harness.endpoints.download_extra_content(1, [14])
    await _drain_background_tasks()

    result = await harness.endpoints.remove_extra_content(1, [14])

    assert result == {"success": True, "removed": 1, "message": "Removed 1 file(s)"}
    assert not os.path.exists(os.path.join(game_dir, "dlc", "Game DLC.nsp"))
    assert os.path.exists(os.path.join(game_dir, "Game.gba"))
    with harness.uow_factory() as uow:
        install = uow.rom_installs.get(1)
    assert install is not None
    assert install.extra_content == ()


async def test_removing_extra_content_of_a_game_that_is_not_installed_is_refused(harness):
    seed_rom(harness, 1, platform_slug="gba")

    result = await harness.endpoints.remove_extra_content(1, [14])

    assert result == {"success": False, "reason": "not_installed", "message": "ROM not installed"}


async def test_an_uninstall_takes_the_extra_content_with_the_game(harness):
    game_dir = _seed_folder_install(harness)
    _seed_server_game(harness)
    await harness.endpoints.download_extra_content(1, [14])
    await _drain_background_tasks()

    result = await harness.endpoints.remove_rom(1)

    assert result["success"] is True
    assert not os.path.exists(game_dir)
