"""Tests for ``SqliteRomInstallRepository`` over the ``rom_installs`` table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.package_install import InstalledTitle
from domain.rom import Rom
from domain.rom_install import RomInstall

if TYPE_CHECKING:
    from adapters.repositories.unit_of_work import SqliteUnitOfWork


def _seed_rom(uow: SqliteUnitOfWork, rom_id: int) -> None:
    uow.roms.save(
        Rom(
            rom_id=rom_id,
            platform_slug="snes",
            name=f"Game {rom_id}",
            fs_name=f"game_{rom_id}.sfc",
            shortcut_app_id=1000 + rom_id,
            last_synced_at="2026-01-01T00:00:00Z",
        )
    )


def _install(
    rom_id: int,
    *,
    path: str = "/roms/snes/game.sfc",
    rom_dir: str | None = None,
) -> RomInstall:
    return RomInstall(
        rom_id=rom_id,
        file_path=path,
        rom_dir=rom_dir,
        platform_slug="snes",
        system="snes",
        installed_at="2026-02-02T00:00:00Z",
    )


class TestRoundTrip:
    def test_all_fields_preserved_multi_file(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 5)
        install = _install(5, path="/roms/psx/FF7/FF7.m3u", rom_dir="/roms/psx/FF7")
        uow.rom_installs.save(install)

        assert uow.rom_installs.get(5) == install

    def test_null_rom_dir_round_trips(self, uow: SqliteUnitOfWork):
        """A single-file ROM's ``rom_dir`` (``None``) persists as SQL NULL and reads back ``None``."""
        _seed_rom(uow, 6)
        install = _install(6, rom_dir=None)
        uow.rom_installs.save(install)

        loaded = uow.rom_installs.get(6)
        assert loaded is not None
        assert loaded.rom_dir is None
        assert loaded == install

    def test_the_fetched_size_round_trips(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 7)
        install = RomInstall.mark_installed(
            rom_id=7,
            file_path="/roms/gc/Game.rvz/Game.rvz",
            rom_dir="/roms/gc/Game.rvz",
            platform_slug="gc",
            system="gc",
            installed_at="2026-02-02T00:00:00Z",
            fetched_size_bytes=1000,
        )
        uow.rom_installs.save(install)

        loaded = uow.rom_installs.get(7)
        assert loaded is not None
        assert loaded.fetched_size_bytes == 1000

    def test_a_title_installed_from_a_package_round_trips_with_its_boot_file(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 8)
        install = _install(8, path="/roms/ps3/G/G.pkg", rom_dir="/roms/ps3/G")
        install.install_from_package(
            InstalledTitle("/drive/game/NPUB30000", "/drive/game/NPUB30000/USRDIR/EBOOT.BIN", "/in/EBOOT.BIN")
        )
        uow.rom_installs.save(install)

        loaded = uow.rom_installs.get(8)
        assert loaded is not None
        assert (loaded.rom_dir, loaded.file_path, loaded.package_boot_file) == (
            "/drive/game/NPUB30000",
            "/drive/game/NPUB30000/USRDIR/EBOOT.BIN",
            "/in/EBOOT.BIN",
        )
        assert _install(9).package_boot_file is None


class TestExtraContent:
    @staticmethod
    def _with_extra_content(rom_id: int) -> RomInstall:
        install = _install(rom_id, path="/roms/switch/Game/Game.nsp", rom_dir="/roms/switch/Game")
        install.add_extra_content(14, "dlc/D.nsp", 50)
        install.add_extra_content(12, "update/U.nsp", 300)
        return install

    def test_the_extra_content_round_trips_with_the_install(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 8)
        uow.rom_installs.save(self._with_extra_content(8))

        loaded = uow.rom_installs.get(8)

        assert loaded is not None
        assert [(e.file_id, e.rel_path, e.size_bytes) for e in loaded.extra_content] == [
            (12, "update/U.nsp", 300),
            (14, "dlc/D.nsp", 50),
        ]
        assert [i.extra_content for i in uow.rom_installs.iter_all()] == [loaded.extra_content]

    def test_a_save_writes_the_extra_content_the_install_holds_now(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 8)
        uow.rom_installs.save(self._with_extra_content(8))
        loaded = uow.rom_installs.get(8)
        assert loaded is not None

        loaded.remove_extra_content(14)
        uow.rom_installs.save(loaded)

        again = uow.rom_installs.get(8)
        assert again is not None
        assert [e.file_id for e in again.extra_content] == [12]

    def test_a_fresh_install_record_saved_over_an_old_one_carries_none(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 8)
        uow.rom_installs.save(self._with_extra_content(8))

        uow.rom_installs.save(_install(8, path="/roms/switch/Game/Game.nsp", rom_dir="/roms/switch/Game"))

        loaded = uow.rom_installs.get(8)
        assert loaded is not None
        assert loaded.extra_content == ()

    def test_a_delete_drops_the_extra_content_with_the_install(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 8)
        uow.rom_installs.save(self._with_extra_content(8))

        uow.rom_installs.delete(8)
        uow.rom_installs.save(_install(8, path="/roms/switch/Game/Game.nsp", rom_dir="/roms/switch/Game"))

        loaded = uow.rom_installs.get(8)
        assert loaded is not None
        assert loaded.extra_content == ()


class TestMiss:
    def test_get_absent_returns_none(self, uow: SqliteUnitOfWork):
        assert uow.rom_installs.get(999) is None


class TestDelete:
    def test_delete_removes_row(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 5)
        uow.rom_installs.save(_install(5))
        uow.rom_installs.delete(5)
        assert uow.rom_installs.get(5) is None

    def test_delete_absent_is_idempotent(self, uow: SqliteUnitOfWork):
        uow.rom_installs.delete(404)
        assert uow.rom_installs.get(404) is None


class TestIteration:
    def test_iter_all_yields_every_install(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 1)
        _seed_rom(uow, 2)
        uow.rom_installs.save(_install(1))
        uow.rom_installs.save(_install(2))

        ids = {install.rom_id for install in uow.rom_installs.iter_all()}
        assert ids == {1, 2}


class TestUpsert:
    def test_save_existing_id_overwrites(self, uow: SqliteUnitOfWork):
        _seed_rom(uow, 1)
        uow.rom_installs.save(_install(1, path="/old"))
        uow.rom_installs.save(_install(1, path="/new"))

        loaded = uow.rom_installs.get(1)
        assert loaded is not None
        assert loaded.file_path == "/new"
