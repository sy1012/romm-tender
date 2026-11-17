"""Tests for packing a save unit into its staged zip and unpacking a zip into the unit."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import zipfile
from typing import TYPE_CHECKING

import pytest

from adapters.save_file import SaveFileAdapter
from adapters.save_unit import SaveUnitAdapter
from domain.save_answer import SaveUnit
from lib.path_safety import PathTraversalError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def adapter() -> SaveUnitAdapter:
    return SaveUnitAdapter(logger=logging.getLogger("test"))


def _write(path: Path, data: bytes, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _wii_save(root: Path) -> SaveUnit:
    _write(root / "banner.bin", b"banner", 1_000)
    _write(root / "wc24" / "data.bin", b"nested", 3_000)
    _write(root / "save.dat", b"progress", 2_000)
    return SaveUnit(root=str(root))


def _zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def _files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace(os.sep, "/"): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestPack:
    def test_the_same_files_give_the_same_bytes(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        first, second = tmp_path / "a.zip", tmp_path / "b.zip"

        assert adapter.pack(unit, str(first)) is True
        assert adapter.pack(unit, str(second)) is True

        assert first.read_bytes() == second.read_bytes()

    def test_entries_are_sorted_relative_names_with_one_fixed_timestamp(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        staged = tmp_path / "stage" / "Game.zip"

        adapter.pack(unit, str(staged))

        with zipfile.ZipFile(staged) as archive:
            infos = archive.infolist()
            assert [info.filename for info in infos] == ["banner.bin", "save.dat", "wc24/data.bin"]
            assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
            assert archive.read("wc24/data.bin") == b"nested"

    def test_the_zip_carries_the_newest_member_s_mtime(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        staged = tmp_path / "Game.zip"

        adapter.pack(unit, str(staged))

        assert staged.stat().st_mtime == 3_000

    def test_the_content_hash_is_romm_s_hash_of_the_folder_s_files(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        staged = tmp_path / "Game.zip"
        adapter.pack(unit, str(staged))
        # RomM's zip hash, worked from the files themselves rather than the zip:
        # MD5 over the sorted ``name:md5(entry)`` lines.
        lines = sorted(f"{name}:{hashlib.md5(data).hexdigest()}" for name, data in _files(tmp_path / "data").items())
        expected = hashlib.md5("\n".join(lines).encode()).hexdigest()

        assert SaveFileAdapter(logger=logging.getLogger("test")).content_hash(str(staged)) == expected

    def test_a_unit_with_no_files_leaves_no_zip_and_removes_a_stale_one(self, adapter, tmp_path):
        root = tmp_path / "data"
        root.mkdir()
        staged = tmp_path / "Game.zip"
        staged.write_bytes(b"stale")

        assert adapter.pack(SaveUnit(root=str(root)), str(staged)) is False
        assert not staged.exists()

    def test_a_missing_root_is_a_unit_with_no_files(self, adapter, tmp_path):
        assert adapter.pack(SaveUnit(root=str(tmp_path / "absent")), str(tmp_path / "Game.zip")) is False
        assert not (tmp_path / "Game.zip").exists()

    def test_a_member_set_packs_only_its_named_members(self, adapter, tmp_path):
        card = tmp_path / "Card A"
        _write(card / "01-GALE-a.gci", b"zelda a")
        _write(card / "01-GALE-b.gci", b"zelda b")
        _write(card / "01-GMSE-a.gci", b"mario")
        staged = tmp_path / "Zelda.zip"

        adapter.pack(SaveUnit(root=str(card), members=("01-GALE-b.gci", "01-GALE-a.gci", "01-GALE-c.gci")), str(staged))

        with zipfile.ZipFile(staged) as archive:
            assert archive.namelist() == ["01-GALE-a.gci", "01-GALE-b.gci"]

    def test_a_link_is_never_packed(self, adapter, tmp_path):
        outside = tmp_path / "outside.bin"
        outside.write_bytes(b"not the game's")
        unit = _wii_save(tmp_path / "data")
        (tmp_path / "data" / "link.bin").symlink_to(outside)
        (tmp_path / "data" / "linkdir").symlink_to(tmp_path)
        staged = tmp_path / "Game.zip"

        adapter.pack(unit, str(staged))

        with zipfile.ZipFile(staged) as archive:
            assert archive.namelist() == ["banner.bin", "save.dat", "wc24/data.bin"]

    def test_no_temporary_file_is_left_beside_the_zip(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        stage = tmp_path / "stage"

        adapter.pack(unit, str(stage / "Game.zip"))

        assert os.listdir(stage) == ["Game.zip"]


class TestUnpackAFolder:
    def test_a_folder_round_trips(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        expected = _files(tmp_path / "data")
        staged = tmp_path / "Game.zip"
        adapter.pack(unit, str(staged))
        shutil.rmtree(tmp_path / "data")

        adapter.unpack(str(staged), unit)

        assert _files(tmp_path / "data") == expected

    def test_the_folder_is_replaced_whole(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "data")
        staged = tmp_path / "Game.zip"
        _zip(staged, {"save.dat": b"from the server"})

        adapter.unpack(str(staged), unit)

        assert _files(tmp_path / "data") == {"save.dat": b"from the server"}
        assert set(os.listdir(tmp_path)) == {"Game.zip", "data"}

    def test_a_missing_folder_and_its_parent_are_created(self, adapter, tmp_path):
        root = tmp_path / "title" / "00010000" / "data"
        staged = tmp_path / "Game.zip"
        _zip(staged, {"banner.bin": b"b"})

        adapter.unpack(str(staged), SaveUnit(root=str(root)))

        assert _files(root) == {"banner.bin": b"b"}

    def test_a_failure_while_moving_in_puts_the_old_folder_back(self, adapter, tmp_path, monkeypatch):
        unit = _wii_save(tmp_path / "data")
        before = _files(tmp_path / "data")
        staged = tmp_path / "Game.zip"
        _zip(staged, {"save.dat": b"new"})
        real_rename = os.rename

        def rename(src, dst):
            if ".unpacking-" in os.path.basename(src) and not src.endswith(".previous"):
                raise OSError("disk full")
            real_rename(src, dst)

        monkeypatch.setattr(os, "rename", rename)

        with pytest.raises(OSError, match="disk full"):
            adapter.unpack(str(staged), unit)

        assert _files(tmp_path / "data") == before
        assert set(os.listdir(tmp_path)) == {"Game.zip", "data"}

    def test_a_failure_while_extracting_leaves_the_folder_and_no_temporary_folder(self, adapter, tmp_path, monkeypatch):
        unit = _wii_save(tmp_path / "data")
        before = _files(tmp_path / "data")
        staged = tmp_path / "Game.zip"
        _zip(staged, {"save.dat": b"new", "z.bin": b"z"})
        real_copy = shutil.copyfileobj
        calls = []

        def copyfileobj(source, out, *args):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("read error")
            real_copy(source, out, *args)

        monkeypatch.setattr(shutil, "copyfileobj", copyfileobj)

        with pytest.raises(OSError, match="read error"):
            adapter.unpack(str(staged), unit)

        assert _files(tmp_path / "data") == before
        assert set(os.listdir(tmp_path)) == {"Game.zip", "data"}


class TestUnpackAMemberSet:
    def _card(self, tmp_path: Path) -> Path:
        card = tmp_path / "Card A"
        _write(card / "01-GALE-a.gci", b"old a")
        _write(card / "01-GALE-b.gci", b"old b")
        _write(card / "01-GMSE-a.gci", b"mario")
        return card

    def test_named_members_are_replaced_and_ones_the_zip_lacks_removed(self, adapter, tmp_path):
        card = self._card(tmp_path)
        staged = tmp_path / "Zelda.zip"
        _zip(staged, {"01-GALE-a.gci": b"new a", "01-GALE-c.gci": b"new c"})

        adapter.unpack(str(staged), SaveUnit(root=str(card), members=("01-GALE-a.gci", "01-GALE-b.gci")))

        assert _files(card) == {"01-GALE-a.gci": b"new a", "01-GALE-c.gci": b"new c", "01-GMSE-a.gci": b"mario"}
        assert set(os.listdir(tmp_path)) == {"Card A", "Zelda.zip"}

    def test_an_entry_in_a_folder_is_refused(self, adapter, tmp_path):
        card = self._card(tmp_path)
        before = _files(card)
        staged = tmp_path / "Zelda.zip"
        _zip(staged, {"sub/01-GALE-a.gci": b"x"})

        with pytest.raises(PathTraversalError):
            adapter.unpack(str(staged), SaveUnit(root=str(card), members=("01-GALE-a.gci",)))

        assert _files(card) == before

    def test_an_entry_over_another_game_s_file_is_refused(self, adapter, tmp_path):
        card = self._card(tmp_path)
        before = _files(card)
        staged = tmp_path / "Zelda.zip"
        _zip(staged, {"01-GALE-a.gci": b"new a", "01-GMSE-a.gci": b"overwrites mario"})

        with pytest.raises(ValueError, match="not this game's"):
            adapter.unpack(str(staged), SaveUnit(root=str(card), members=("01-GALE-a.gci",)))

        assert _files(card) == before
        assert set(os.listdir(tmp_path)) == {"Card A", "Zelda.zip"}


class TestUnpackRefusesAnEntryOutsideTheRoot:
    @pytest.mark.parametrize(
        "name",
        ["../escape.bin", "/abs/escape.bin", "a/../../escape.bin", "..\\escape.bin", "a//b.bin", "./a.bin"],
    )
    @pytest.mark.parametrize("members", [None, ("save.dat",)])
    def test_nothing_is_written(self, adapter, tmp_path, name, members):
        root = tmp_path / "saves" / "data"
        _write(root / "save.dat", b"kept")
        staged = tmp_path / "Game.zip"
        with zipfile.ZipFile(staged, "w") as archive:
            archive.writestr("save.dat", b"new")
            archive.writestr(zipfile.ZipInfo(name), b"evil")

        with pytest.raises(PathTraversalError):
            adapter.unpack(str(staged), SaveUnit(root=str(root), members=members))

        assert _files(root) == {"save.dat": b"kept"}
        assert os.listdir(tmp_path / "saves") == ["data"]
        assert not (tmp_path / "escape.bin").exists()


class TestTheArchiveFolder:
    """A unit laid out as other RomM clients lay it: every entry under the folder's own name."""

    def test_every_entry_sits_under_the_archive_folder(self, adapter, tmp_path):
        root = tmp_path / "00010000" / "52534245"
        _write(root / "data" / "banner.bin", b"banner")
        _write(root / "data" / "save.dat", b"progress")
        unit = SaveUnit(root=str(root), archive_folder="52534245")
        zip_path = tmp_path / "game.zip"

        adapter.pack(unit, str(zip_path))

        with zipfile.ZipFile(zip_path) as archive:
            assert archive.namelist() == ["52534245/data/banner.bin", "52534245/data/save.dat"]

    def test_the_folder_name_is_stripped_on_the_way_back(self, adapter, tmp_path):
        root = tmp_path / "00010000" / "52534245"
        zip_path = tmp_path / "game.zip"
        _zip(zip_path, {"52534245/data/save.dat": b"progress"})

        adapter.unpack(str(zip_path), SaveUnit(root=str(root), archive_folder="52534245"))

        assert _files(root) == {"data/save.dat": b"progress"}

    @pytest.mark.parametrize("name", ["data/save.dat", "OTHER/data/save.dat", "52534245", "52534245x/save.dat"])
    def test_a_zip_laid_out_otherwise_is_refused_with_nothing_written(self, adapter, tmp_path, name):
        root = tmp_path / "00010000" / "52534245"
        _write(root / "data" / "save.dat", b"mine")
        zip_path = tmp_path / "game.zip"
        _zip(zip_path, {name: b"theirs"})

        with pytest.raises(PathTraversalError):
            adapter.unpack(str(zip_path), SaveUnit(root=str(root), archive_folder="52534245"))

        assert _files(root) == {"data/save.dat": b"mine"}
        assert sorted(p.name for p in root.parent.iterdir()) == ["52534245"]

    def test_a_round_trip_through_the_archive_folder_gives_the_same_files(self, adapter, tmp_path):
        root = tmp_path / "title" / "52534245"
        _write(root / "data" / "banner.bin", b"banner")
        _write(root / "data" / "nested" / "x.bin", b"x")
        unit = SaveUnit(root=str(root), archive_folder="52534245")
        zip_path = tmp_path / "game.zip"
        before = _files(root)

        adapter.pack(unit, str(zip_path))
        shutil.rmtree(root)
        adapter.unpack(str(zip_path), unit)

        assert _files(root) == before


class TestClear:
    def test_a_folder_unit_s_root_and_everything_below_it_are_removed(self, adapter, tmp_path):
        unit = _wii_save(tmp_path / "title" / "data")
        _write(tmp_path / "title" / "content.bin", b"beside the root")

        adapter.clear(unit)

        assert not (tmp_path / "title" / "data").exists()
        assert (tmp_path / "title" / "content.bin").read_bytes() == b"beside the root"

    def test_a_member_set_loses_only_its_named_members(self, adapter, tmp_path):
        card = tmp_path / "Card A"
        _write(card / "01-GALE-a.gci", b"zelda a")
        _write(card / "01-GALE-b.gci", b"zelda b")
        _write(card / "01-GMSE-a.gci", b"mario")

        adapter.clear(SaveUnit(root=str(card), members=("01-GALE-a.gci", "01-GALE-b.gci", "01-GALE-c.gci")))

        assert _files(card) == {"01-GMSE-a.gci": b"mario"}

    def test_a_folder_root_that_is_a_link_is_refused_and_nothing_is_removed(self, adapter, tmp_path):
        target = tmp_path / "elsewhere"
        _write(target / "save.dat", b"kept")
        root = tmp_path / "data"
        root.symlink_to(target)

        with pytest.raises(OSError, match="link"):
            adapter.clear(SaveUnit(root=str(root)))

        assert root.is_symlink()
        assert _files(target) == {"save.dat": b"kept"}

    def test_missing_files_are_fine(self, adapter, tmp_path):
        adapter.clear(SaveUnit(root=str(tmp_path / "absent")))
        adapter.clear(SaveUnit(root=str(tmp_path / "absent"), members=("a.gci",)))

        assert not (tmp_path / "absent").exists()


class TestPrefixedFolders:
    """A PSP game's save folders in PPSSPP's SAVEDATA, which other games' folders share, picked by the game's id."""

    _PREFIX = "ULUS10064"

    def _savedata(self, tmp_path: Path) -> Path:
        savedata = tmp_path / "PSP" / "SAVEDATA"
        _write(savedata / "ULUS10064DATA00" / "PARAM.SFO", b"sfo 0", 1_000)
        _write(savedata / "ULUS10064DATA00" / "DATA.BIN", b"progress 0", 3_000)
        _write(savedata / "ULUS10064DATA01" / "PARAM.SFO", b"sfo 1", 2_000)
        _write(savedata / "ULUS10064INSTALL" / "CACHE.BIN", b"installed data")
        _write(savedata / "ULES00151DATA" / "PARAM.SFO", b"another game")
        return savedata

    def _unit(self, savedata: Path, members: tuple[str, ...] = ("ULUS10064DATA00", "ULUS10064DATA01")) -> SaveUnit:
        return SaveUnit(root=str(savedata), members=members, prefix=self._PREFIX)

    def test_each_member_folder_packs_at_the_zip_s_top(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)
        staged = tmp_path / "Game.zip"

        assert adapter.pack(self._unit(savedata), str(staged)) is True

        with zipfile.ZipFile(staged) as archive:
            assert archive.namelist() == [
                "ULUS10064DATA00/DATA.BIN",
                "ULUS10064DATA00/PARAM.SFO",
                "ULUS10064DATA01/PARAM.SFO",
            ]
        assert os.stat(staged).st_mtime == 3_000

    def test_a_unit_with_no_member_folders_leaves_no_zip(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)
        staged = tmp_path / "Game.zip"

        assert adapter.pack(self._unit(savedata, members=()), str(staged)) is False
        assert not staged.exists()

    def test_a_member_folder_that_is_a_link_is_not_packed(self, adapter, tmp_path):
        savedata = tmp_path / "SAVEDATA"
        _write(tmp_path / "elsewhere" / "secret.bin", b"secret")
        savedata.mkdir()
        (savedata / "ULUS10064DATA00").symlink_to(tmp_path / "elsewhere")

        assert adapter.pack(self._unit(savedata, members=("ULUS10064DATA00",)), str(tmp_path / "Game.zip")) is False

    def test_a_round_trip_gives_the_same_files_and_leaves_the_other_folders(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)
        before = _files(savedata)
        staged = tmp_path / "Game.zip"
        adapter.pack(self._unit(savedata), str(staged))
        adapter.clear(self._unit(savedata))

        adapter.unpack(str(staged), self._unit(savedata, members=()))

        assert _files(savedata) == before
        assert set(os.listdir(tmp_path / "PSP")) == {"SAVEDATA"}

    def test_a_restore_replaces_the_members_and_leaves_another_game_and_the_installed_data(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA00/PARAM.SFO": b"new sfo", "ULUS10064DATA02/PARAM.SFO": b"new slot"})

        adapter.unpack(str(staged), self._unit(savedata))

        assert _files(savedata) == {
            "ULUS10064DATA00/PARAM.SFO": b"new sfo",
            "ULUS10064DATA02/PARAM.SFO": b"new slot",
            "ULUS10064INSTALL/CACHE.BIN": b"installed data",
            "ULES00151DATA/PARAM.SFO": b"another game",
        }
        assert set(os.listdir(tmp_path / "PSP")) == {"SAVEDATA"}

    def test_a_folder_the_zip_brings_over_one_that_is_not_a_member_is_refused(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)
        before = _files(savedata)
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA00/PARAM.SFO": b"new", "ULUS10064INSTALL/CACHE.BIN": b"overwrites"})

        with pytest.raises(ValueError, match="not this game's save"):
            adapter.unpack(str(staged), self._unit(savedata))

        assert _files(savedata) == before
        assert set(os.listdir(tmp_path / "PSP")) == {"SAVEDATA"}

    def test_a_case_different_folder_name_still_matches_the_prefix(self, adapter, tmp_path):
        savedata = tmp_path / "SAVEDATA"
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ulus10064data00/PARAM.SFO": b"sfo"})

        adapter.unpack(str(staged), self._unit(savedata, members=()))

        assert _files(savedata) == {"ulus10064data00/PARAM.SFO": b"sfo"}

    def test_a_restore_onto_a_fresh_memory_stick_creates_the_folder(self, adapter, tmp_path):
        savedata = tmp_path / "memstick" / "PSP" / "SAVEDATA"
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA00/PARAM.SFO": b"sfo", "ULUS10064DATA00/sub/DATA.BIN": b"data"})

        adapter.unpack(str(staged), self._unit(savedata, members=()))

        assert _files(savedata) == {"ULUS10064DATA00/PARAM.SFO": b"sfo", "ULUS10064DATA00/sub/DATA.BIN": b"data"}
        assert os.listdir(tmp_path / "memstick" / "PSP") == ["SAVEDATA"]

    def test_a_root_reached_through_a_link_is_written_where_the_link_leads(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path / "sd")
        link = tmp_path / "config" / "PSP" / "SAVEDATA"
        link.parent.mkdir(parents=True)
        link.symlink_to(savedata)
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA00/PARAM.SFO": b"new"})

        adapter.unpack(str(staged), self._unit(link, members=("ULUS10064DATA00",)))

        assert _files(savedata)["ULUS10064DATA00/PARAM.SFO"] == b"new"
        assert "ULUS10064DATA01/PARAM.SFO" in _files(savedata)
        assert os.listdir(tmp_path / "config" / "PSP") == ["SAVEDATA"]
        assert os.listdir(tmp_path / "sd" / "PSP") == ["SAVEDATA"]

    @pytest.mark.parametrize(
        "name",
        [
            "ULES00151DATA/PARAM.SFO",
            "PARAM.SFO",
            "ULUS10064DATA00",
            "ULUS10064DATA00/../escape.bin",
            "../ULUS10064DATA00/escape.bin",
            "/ULUS10064DATA00/escape.bin",
            "ULUS10064DATA00\\escape.bin",
            "ULUS10064DATA00//a.bin",
            "ULUS1006/a.bin",
        ],
    )
    def test_an_entry_outside_a_prefixed_folder_is_refused_with_nothing_written(self, adapter, tmp_path, name):
        savedata = self._savedata(tmp_path)
        before = _files(savedata)
        staged = tmp_path / "Game.zip"
        with zipfile.ZipFile(staged, "w") as archive:
            archive.writestr("ULUS10064DATA00/PARAM.SFO", b"new")
            archive.writestr(zipfile.ZipInfo(name), b"evil")

        with pytest.raises(PathTraversalError):
            adapter.unpack(str(staged), self._unit(savedata))

        assert _files(savedata) == before
        assert set(os.listdir(tmp_path / "PSP")) == {"SAVEDATA"}
        assert not (tmp_path / "escape.bin").exists()

    def test_a_member_that_is_a_link_is_refused_with_nothing_written(self, adapter, tmp_path):
        savedata = tmp_path / "SAVEDATA"
        _write(tmp_path / "elsewhere" / "kept.bin", b"kept")
        savedata.mkdir()
        (savedata / "ULUS10064DATA00").symlink_to(tmp_path / "elsewhere")
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA01/PARAM.SFO": b"new"})

        with pytest.raises(OSError, match="link"):
            adapter.unpack(str(staged), self._unit(savedata, members=("ULUS10064DATA00",)))

        assert os.listdir(savedata) == ["ULUS10064DATA00"]

        assert _files(tmp_path / "elsewhere") == {"kept.bin": b"kept"}
        assert (savedata / "ULUS10064DATA00").is_symlink()

    def test_a_failure_while_moving_in_puts_the_members_back(self, adapter, tmp_path, monkeypatch):
        savedata = self._savedata(tmp_path)
        before = _files(savedata)
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA00/PARAM.SFO": b"new 0", "ULUS10064DATA01/PARAM.SFO": b"new 1"})
        real_rename = os.rename

        def rename(src, dst):
            if ".unpacking-" in src and os.path.basename(src) == "ULUS10064DATA01":
                raise OSError("disk full")
            real_rename(src, dst)

        monkeypatch.setattr(os, "rename", rename)

        with pytest.raises(OSError, match="disk full"):
            adapter.unpack(str(staged), self._unit(savedata))

        assert _files(savedata) == before
        assert set(os.listdir(tmp_path / "PSP")) == {"SAVEDATA"}

    def test_a_failed_put_back_keeps_the_moved_out_folders(self, adapter, tmp_path, monkeypatch):
        savedata = self._savedata(tmp_path)
        staged = tmp_path / "Game.zip"
        _zip(staged, {"ULUS10064DATA00/PARAM.SFO": b"new 0"})
        real_rename = os.rename

        def rename(src, dst):
            if ".unpacking-" in src or ".previous-" in src:
                raise OSError("disk gone")
            real_rename(src, dst)

        monkeypatch.setattr(os, "rename", rename)

        with pytest.raises(OSError, match="disk gone"):
            adapter.unpack(str(staged), self._unit(savedata))

        (aside,) = [name for name in os.listdir(tmp_path / "PSP") if ".previous-" in name]
        assert _files(tmp_path / "PSP" / aside) == {
            "ULUS10064DATA00/DATA.BIN": b"progress 0",
            "ULUS10064DATA00/PARAM.SFO": b"sfo 0",
            "ULUS10064DATA01/PARAM.SFO": b"sfo 1",
        }

    def test_clear_removes_only_the_member_folders(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)

        adapter.clear(self._unit(savedata, members=("ULUS10064DATA00", "ULUS10064DATA01", "ULUS10064DATA09")))

        assert _files(savedata) == {
            "ULUS10064INSTALL/CACHE.BIN": b"installed data",
            "ULES00151DATA/PARAM.SFO": b"another game",
        }

    def test_clear_refuses_a_member_that_is_a_link_and_removes_nothing(self, adapter, tmp_path):
        savedata = self._savedata(tmp_path)
        _write(tmp_path / "elsewhere" / "kept.bin", b"kept")
        (savedata / "ULUS10064DATA02").symlink_to(tmp_path / "elsewhere")
        before = _files(savedata)

        with pytest.raises(OSError, match="link"):
            adapter.clear(self._unit(savedata, members=("ULUS10064DATA00", "ULUS10064DATA02")))

        assert _files(savedata) == before
        assert _files(tmp_path / "elsewhere") == {"kept.bin": b"kept"}
