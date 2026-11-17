"""A save unit syncs as the zip staged for it: packed before it is read, unpacked once written.

Driven end to end through the real save service, the real save-file and
save-unit adapters and the real gavel core, with the resolver's answer stated
by ``FakeSaveLocationReader``.
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Any, ClassVar

import pytest
from fakes.fake_save_location_reader import FakeSaveLocationReader

from domain.rom_save_sync_state import RomSaveSyncState
from domain.save_answer import SaveUnit, unit_answer
from domain.save_backup import BACKUP_DIR_NAME
from lib.errors import Refused
from services.saves._save_state import read_save_state_or_new, write_save_state
from tests.services.saves._helpers import (
    _do_sync,
    _enable_sync_with_device,
    _get_save_state,
    _install_rom,
    make_service,
)

_SYSTEM = "wii"
_STEM = "Wii Sports"
_ZIP = f"{_STEM}.zip"


def _root(tmp_path) -> Any:
    return tmp_path / "nand" / "title" / "00010000" / "52535045" / "data"


def _staging(tmp_path) -> Any:
    return tmp_path / "data" / "save-units" / "42"


def _service(tmp_path, *, members: tuple[str, ...] | None = None) -> tuple[Any, Any]:
    svc, fake = make_service(tmp_path)
    _enable_sync_with_device(svc, "device-1")
    _install_rom(svc, tmp_path, system=_SYSTEM, file_name=f"{_STEM}.rvz")
    write_save_state(svc._uow_factory, 42, RomSaveSyncState(active_slot="default", slot_confirmed=True))
    reader = svc._rom_info._save_locations
    assert isinstance(reader, FakeSaveLocationReader)
    reader.answer_with(
        _SYSTEM,
        unit_answer(
            unit=SaveUnit(root=str(_root(tmp_path)), members=members),
            emulator="Dolphin (Standalone)",
            emulator_identity="DOLPHIN",
            content_installed=True,
        ),
    )
    return svc, fake


def _write_unit(tmp_path, files: dict[str, bytes], mtime: float = 1_700_000_000) -> None:
    for name, data in files.items():
        path = _root(tmp_path) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (mtime, mtime))


def _unit_files(tmp_path) -> dict[str, bytes]:
    root = _root(tmp_path)
    return {
        str(path.relative_to(root)).replace(os.sep, "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _uploads(fake) -> list[tuple[Any, ...]]:
    return [call for call in fake.call_log if call[0] == "upload_save"]


def _seed_server_zip(
    svc, fake, tmp_path, files: dict[str, bytes], *, save_id: int, updated_at: str, slot: str | None = None
) -> None:
    """A ``<stem>.zip`` save in *slot*, else the ROM's active slot, uploaded by another device."""
    content = _zip_bytes(files)
    scratch = tmp_path / f"server-{save_id}.zip"
    scratch.write_bytes(content)
    state = read_save_state_or_new(svc._uow_factory, 42)
    fake.saves[save_id] = {
        "id": save_id,
        "rom_id": 42,
        "file_name": _ZIP,
        "file_name_no_tags": _STEM,
        "file_extension": "zip",
        "slot": slot or state.active_slot,
        "updated_at": updated_at,
        "file_size_bytes": len(content),
        "emulator": "dolphin",
        "content_hash": svc._save_file_store.content_hash(str(scratch)),
        "download_path": f"/saves/{_ZIP}",
    }
    fake.set_server_save_content(save_id, content)


def _name_uploads_as_romm_does(fake) -> None:
    """RomM answers a save's ``file_extension`` from its name; the fake leaves it out."""
    for save in fake.saves.values():
        save.setdefault("file_extension", "zip")


class TestAFirstSyncUploadsTheUnit:
    def test_the_folder_is_uploaded_as_the_staged_zip(self, tmp_path):
        svc, fake = _service(tmp_path)
        _write_unit(tmp_path, {"banner.bin": b"banner", "save.dat": b"progress"})

        uploaded, downloaded, errors, _ = _do_sync(svc, 42)

        assert (uploaded, downloaded, errors) == (1, 0, [])
        ((_name, (_rom_id, file_path, emulator), _kwargs),) = _uploads(fake)
        assert file_path == str(_staging(tmp_path) / _ZIP)
        assert emulator == "dolphin"
        (stored,) = fake.saves.values()
        assert stored["file_name"].startswith(_STEM)
        assert stored["file_name"].endswith(".zip")
        with zipfile.ZipFile(io.BytesIO(fake._save_content[stored["id"]])) as archive:
            assert archive.namelist() == ["banner.bin", "save.dat"]

    def test_the_recorded_tag_is_the_emulator_s_identity(self, tmp_path):
        svc, _fake = _service(tmp_path)
        _write_unit(tmp_path, {"save.dat": b"progress"})

        _do_sync(svc, 42)

        state = _get_save_state(svc, 42)
        assert state is not None
        assert state.emulator == "dolphin"
        assert set(state.files) == {_ZIP}

    def test_an_unchanged_unit_is_skipped_on_the_next_sync(self, tmp_path):
        svc, fake = _service(tmp_path)
        _write_unit(tmp_path, {"banner.bin": b"banner", "save.dat": b"progress"})
        _do_sync(svc, 42)
        _name_uploads_as_romm_does(fake)

        uploaded, downloaded, errors, conflicts = _do_sync(svc, 42)

        assert (uploaded, downloaded, errors, conflicts) == (0, 0, [], [])
        assert len(_uploads(fake)) == 1

    def test_a_changed_member_is_uploaded_again(self, tmp_path):
        svc, fake = _service(tmp_path)
        _write_unit(tmp_path, {"banner.bin": b"banner", "save.dat": b"progress"})
        _do_sync(svc, 42)
        _name_uploads_as_romm_does(fake)
        _write_unit(tmp_path, {"save.dat": b"more progress"}, mtime=1_800_000_000)

        uploaded, _downloaded, errors, _ = _do_sync(svc, 42)

        assert (uploaded, errors) == (1, [])


class TestADownloadIsUnpackedIntoTheUnit:
    def test_a_server_zip_creates_the_folder(self, tmp_path):
        svc, fake = _service(tmp_path)
        files = {"banner.bin": b"banner", "wc24/data.bin": b"nested", "save.dat": b"server progress"}
        _seed_server_zip(svc, fake, tmp_path, files, save_id=100, updated_at="2026-02-17T06:00:00Z")

        uploaded, downloaded, errors, _ = _do_sync(svc, 42)

        assert (uploaded, downloaded, errors) == (0, 1, [])
        assert _unit_files(tmp_path) == files

    def test_a_newer_server_save_replaces_the_folder_and_keeps_the_old_one_backed_up(self, tmp_path):
        svc, fake = _service(tmp_path)
        _write_unit(tmp_path, {"banner.bin": b"banner", "old.dat": b"old progress"})
        _do_sync(svc, 42)
        _name_uploads_as_romm_does(fake)
        newer = {"banner.bin": b"banner", "save.dat": b"newer progress"}
        _seed_server_zip(svc, fake, tmp_path, newer, save_id=2000, updated_at="2099-01-01T00:00:00Z")

        uploaded, downloaded, errors, conflicts = _do_sync(svc, 42)

        assert (uploaded, downloaded, errors, conflicts) == (0, 1, [], [])
        assert _unit_files(tmp_path) == newer
        (backup,) = os.listdir(_staging(tmp_path) / BACKUP_DIR_NAME)
        with zipfile.ZipFile(_staging(tmp_path) / BACKUP_DIR_NAME / backup) as archive:
            assert {name: archive.read(name) for name in archive.namelist()} == {
                "banner.bin": b"banner",
                "old.dat": b"old progress",
            }

    def test_a_downloaded_unit_is_not_uploaded_back(self, tmp_path):
        svc, fake = _service(tmp_path)
        _seed_server_zip(svc, fake, tmp_path, {"save.dat": b"server"}, save_id=100, updated_at="2026-02-17T06:00:00Z")
        _do_sync(svc, 42)

        uploaded, downloaded, errors, conflicts = _do_sync(svc, 42)

        assert (uploaded, downloaded, errors, conflicts) == (0, 0, [], [])

    def test_a_zip_that_cannot_be_unpacked_fails_the_download_and_leaves_the_unit(self, tmp_path):
        svc, fake = _service(tmp_path)
        _write_unit(tmp_path, {"save.dat": b"local"})
        _do_sync(svc, 42)
        _name_uploads_as_romm_does(fake)
        _seed_server_zip(svc, fake, tmp_path, {"../escape.dat": b"x"}, save_id=2000, updated_at="2099-01-01T00:00:00Z")

        _uploaded, downloaded, errors, _ = _do_sync(svc, 42)

        assert downloaded == 0
        assert errors
        assert _unit_files(tmp_path) == {"save.dat": b"local"}
        assert not (tmp_path / "nand" / "title" / "00010000" / "52535045" / "escape.dat").exists()
        state = _get_save_state(svc, 42)
        assert state is not None
        assert state.files[_ZIP].tracked_save_id != 2000


class TestAMemberSetUnit:
    def test_only_the_named_members_are_carried(self, tmp_path):
        svc, fake = _service(tmp_path, members=("01-GALE-a.gci",))
        _write_unit(tmp_path, {"01-GALE-a.gci": b"zelda", "01-GMSE-a.gci": b"mario"})

        _do_sync(svc, 42)

        (stored,) = fake.saves.values()
        with zipfile.ZipFile(io.BytesIO(fake._save_content[stored["id"]])) as archive:
            assert archive.namelist() == ["01-GALE-a.gci"]


class TestAnAnswerWithoutAUnit:
    def test_no_staging_folder_is_made(self, tmp_path):
        svc, fake = make_service(tmp_path)
        _enable_sync_with_device(svc, "device-1")
        _install_rom(svc, tmp_path)
        saves = tmp_path / "saves" / "gba"
        saves.mkdir(parents=True)
        (saves / "pokemon.srm").write_bytes(b"battery")

        uploaded, _downloaded, errors, _ = _do_sync(svc, 42)

        assert (uploaded, errors) == (1, [])
        assert not (tmp_path / "data").exists()
        ((_name, (_rom_id, file_path, emulator), _kwargs),) = _uploads(fake)
        assert file_path == str(saves / "pokemon.srm")
        assert emulator == "retroarch"


class TestTheRecordedTagIsKept:
    def test_a_download_keeps_the_tag_already_recorded(self, tmp_path):
        svc, fake = _service(tmp_path)
        write_save_state(
            svc._uow_factory,
            42,
            RomSaveSyncState(active_slot="default", slot_confirmed=True, emulator="dolphin-recorded"),
        )
        _seed_server_zip(svc, fake, tmp_path, {"save.dat": b"server"}, save_id=100, updated_at="2026-02-17T06:00:00Z")

        _uploaded, downloaded, _errors, _ = _do_sync(svc, 42)

        assert downloaded == 1
        state = _get_save_state(svc, 42)
        assert state is not None
        assert state.emulator == "dolphin-recorded"


class TestARollbackRestoresTheWholeUnit:
    async def test_every_member_comes_back_from_the_chosen_version(self, tmp_path):
        svc, fake = _service(tmp_path)
        older = {"banner.bin": b"banner", "save.dat": b"chapter one"}
        newer = {"banner.bin": b"banner", "save.dat": b"chapter two", "extra.dat": b"extra"}
        _seed_server_zip(svc, fake, tmp_path, older, save_id=100, updated_at="2026-02-17T06:00:00Z")
        _seed_server_zip(svc, fake, tmp_path, newer, save_id=101, updated_at="2026-02-18T06:00:00Z")
        _do_sync(svc, 42)
        assert _unit_files(tmp_path) == newer

        result = await svc.rollback_to_version(42, "default", 100)

        assert result["status"] == "ok", result
        assert _unit_files(tmp_path) == older


def _backed_up_zips(tmp_path) -> list[dict[str, bytes]]:
    backups = _staging(tmp_path) / BACKUP_DIR_NAME
    found = []
    for path in sorted(backups.iterdir()) if backups.exists() else []:
        with zipfile.ZipFile(path) as archive:
            found.append({name: archive.read(name) for name in archive.namelist()})
    return found


def _synced_unit(tmp_path, files: dict[str, bytes]) -> tuple[Any, Any]:
    svc, fake = _service(tmp_path)
    _write_unit(tmp_path, files)
    _do_sync(svc, 42)
    _name_uploads_as_romm_does(fake)
    return svc, fake


class TestASlotSwitchSetsTheUnitAside:
    _OLD: ClassVar[dict[str, bytes]] = {"banner.bin": b"banner", "save.dat": b"old slot"}

    async def test_a_switch_to_an_empty_slot_leaves_the_unit_empty_and_its_files_backed_up(self, tmp_path):
        svc, _fake = _synced_unit(tmp_path, self._OLD)

        result = await svc.switch_slot(42, "empty")

        assert isinstance(result, dict), result
        assert result["success"] is True
        assert not _root(tmp_path).exists()
        assert _backed_up_zips(tmp_path) == [self._OLD]

    async def test_a_switch_to_a_slot_with_a_save_gives_that_save_s_files(self, tmp_path):
        svc, fake = _synced_unit(tmp_path, self._OLD)
        other = {"save.dat": b"other slot"}
        _seed_server_zip(svc, fake, tmp_path, other, save_id=3000, updated_at="2026-02-17T06:00:00Z", slot="other")

        result = await svc.switch_slot(42, "other")

        assert isinstance(result, dict), result
        assert _unit_files(tmp_path) == other
        assert _backed_up_zips(tmp_path) == [self._OLD]

    async def test_a_set_aside_that_fails_leaves_the_unit_untouched(self, tmp_path, monkeypatch):
        svc, _fake = _synced_unit(tmp_path, self._OLD)

        def back_up_save_file(*_args: object, **_kwargs: object) -> bool:
            raise PermissionError(".romm-backup is read-only")

        monkeypatch.setattr(svc._save_backup, "back_up_save_file", back_up_save_file)

        with pytest.raises(Refused):
            await svc.switch_slot(42, "empty")

        assert _unit_files(tmp_path) == self._OLD


class TestDeletingLocalSavesClearsTheUnit:
    async def test_the_game_s_delete_removes_the_unit_and_its_staged_zip(self, tmp_path):
        svc, _fake = _synced_unit(tmp_path, {"banner.bin": b"banner", "save.dat": b"progress"})

        result = await svc.delete_local_saves(42)

        assert isinstance(result, dict), result
        assert result["deleted_count"] == 1
        assert not _root(tmp_path).exists()
        assert not (_staging(tmp_path) / _ZIP).exists()

    async def test_the_platform_s_delete_removes_the_unit(self, tmp_path):
        svc, _fake = _synced_unit(tmp_path, {"save.dat": b"progress"})

        await svc.delete_platform_saves(_SYSTEM)

        assert not _root(tmp_path).exists()

    async def test_a_member_set_delete_leaves_the_other_games_files(self, tmp_path):
        svc, _fake = _service(tmp_path, members=("01-GALE-a.gci",))
        _write_unit(tmp_path, {"01-GALE-a.gci": b"zelda", "01-GMSE-a.gci": b"mario"})

        await svc.delete_local_saves(42)

        assert _unit_files(tmp_path) == {"01-GMSE-a.gci": b"mario"}

    async def test_a_zip_that_could_not_be_removed_leaves_the_unit(self, tmp_path, monkeypatch):
        svc, _fake = _synced_unit(tmp_path, {"save.dat": b"progress"})

        def remove_file(path: str) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(svc._save_file_store, "remove_file", remove_file)

        await svc.delete_local_saves(42)

        assert _unit_files(tmp_path) == {"save.dat": b"progress"}
