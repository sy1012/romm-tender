"""A recorded download whose content is a package, installed into its emulator (ADR-0051).

The step runs over the real download file store under ``tmp_path``, a fake
reading of the resolver's answer and a fake install that writes — or does not
write — the boot file the answer names.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from fakes.fake_package_install import FakePackageInstallControl, FakePackageInstallReader, write_boot_file
from fakes.fake_retrodeck_folders import FakeRetroDeckFolders
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.system_time import FakeClock

from adapters.download_file import DownloadFileAdapter
from domain.package_install import (
    COMMAND_INCOMPLETE,
    DID_NOT_FINISH,
    NO_BOOT_FILE,
    NOT_STARTED,
    InstalledTitle,
    PackageInstallPlan,
    PackageInstallRefused,
)
from domain.rom import Rom
from domain.rom_install import RomInstall
from services.downloads import DownloadPackageInstall, DownloadPackageInstallConfig, DownloadQueue, DownloadQueueConfig
from services.downloads.package_install import PackageInstalled, PackageNotInstalled

if TYPE_CHECKING:
    from pathlib import Path

_ARGV = ("flatpak", "run", "--command=rpcs3", "net.retrodeck.retrodeck", "--headless", "--installpkg", "<folder>")


class _World:
    def __init__(self, tmp_path: Path, emit: Any) -> None:
        self.roms = tmp_path / "retrodeck" / "roms"
        self.download = self.roms / "ps3" / "Game"
        self.download.mkdir(parents=True)
        (self.download / "UP0001-NPUB30000_00-GAME.pkg").write_bytes(b"pkg")
        (self.download / "UP0001-NPUB30000_00-GAME-edat.pkg").write_bytes(b"edat")
        self.drive = tmp_path / "rpcs3" / "dev_hdd0"
        self.savedata = self.drive / "home" / "00000001" / "savedata" / "NPUB30000-SAVE"
        self.savedata.mkdir(parents=True)
        self.title = InstalledTitle(
            str(self.drive / "game" / "NPUB30000"),
            str(self.drive / "game" / "NPUB30000" / "USRDIR" / "EBOOT.BIN"),
            "/var/config/rpcs3/dev_hdd0/game/NPUB30000/USRDIR/EBOOT.BIN",
        )
        self.uow = FakeUnitOfWork()
        self.uow.roms.save(
            Rom(rom_id=7, platform_slug="ps3", name="Game", fs_name="Game", shortcut_app_id=None, last_synced_at="now")
        )
        self.uow.rom_installs.save(
            RomInstall.mark_installed(
                rom_id=7,
                file_path=str(self.download / "UP0001-NPUB30000_00-GAME.pkg"),
                rom_dir=str(self.download),
                platform_slug="ps3",
                system="ps3",
                installed_at="2026-11-18T00:00:00",
            )
        )
        self.reader = FakePackageInstallReader(PackageInstallPlan(argv=_ARGV, title=self.title, installer="RPCS3"))
        self.control = FakePackageInstallControl()
        self.queue = DownloadQueue(
            config=DownloadQueueConfig(
                loop=asyncio.get_running_loop(),
                emit=emit,
                clock=FakeClock(now=datetime(2026, 1, 1, tzinfo=UTC)),
                logger=logging.getLogger("test"),
            )
        )
        self.queue.enqueue(7, {"rom_id": 7, "status": "downloading"})
        self.step = DownloadPackageInstall(
            config=DownloadPackageInstallConfig(
                package_installs=self.reader,
                install_control=self.control,
                download_file_store=DownloadFileAdapter(),
                retrodeck_folders=FakeRetroDeckFolders(roms=str(self.roms)),
                uow_factory=FakeUnitOfWorkFactory(self.uow),
                queue=self.queue,
                loop=asyncio.get_running_loop(),
                logger=logging.getLogger("test"),
                timeout_seconds=5,
            )
        )

    async def install(self) -> Any:
        return await self.step.install(7, "Game", "PlayStation 3", "Game.pkg")

    def record(self) -> RomInstall:
        install = self.uow.rom_installs.get(7)
        assert install is not None
        return install


@pytest.fixture
async def world(tmp_path, emit) -> _World:
    return _World(tmp_path, emit)


class TestAnInstallThatSucceeds:
    async def test_the_record_names_the_installed_title_and_the_download_goes(self, world):
        world.control.effect = write_boot_file(world.title.boot_file)

        outcome = await world.install()

        assert outcome == PackageInstalled(world.title.boot_file)
        record = world.record()
        assert (record.rom_dir, record.file_path, record.package_boot_file) == (
            world.title.folder,
            world.title.boot_file,
            world.title.boot_file_in_emulator,
        )
        assert not world.download.exists()
        assert (world.roms / "ps3").is_dir()
        assert world.savedata.is_dir()

    async def test_the_whole_download_folder_is_installed_with_the_folder_granted(self, world):
        world.control.effect = write_boot_file(world.title.boot_file)

        await world.install()

        assert world.reader.asked == [("ps3", str(world.download), (str(world.download),))]
        assert world.control.ran == [_ARGV]

    async def test_packages_one_folder_down_beside_a_playlist_are_installed_from_their_own_folder(self, world):
        """RPCS3 reads only the folder it is handed; a RomM game can keep its packages one folder below its own."""
        inner = world.download / "NPUB30000"
        inner.mkdir()
        for package in world.download.glob("*.pkg"):
            package.rename(inner / package.name)
        (world.download / "Game.m3u").write_text("NPUB30000")
        world.control.effect = write_boot_file(world.title.boot_file)

        await world.install()

        assert world.reader.asked == [("ps3", str(inner), (str(world.download),))]
        assert not world.download.exists()

    async def test_the_queue_says_it_is_installing_while_it_runs(self, world, emit):
        world.control.effect = write_boot_file(world.title.boot_file)

        await world.install()
        await asyncio.sleep(0)

        frames = [call.args[1] for call in emit.call_args_list if call.args[0] == "download_progress"]
        assert [frame["status"] for frame in frames] == ["installing"]
        assert world.queue.entries[7]["status"] == "installing"

    async def test_the_exit_status_says_nothing(self, world):
        world.control.effect = write_boot_file(world.title.boot_file)
        world.control.status = 1

        assert isinstance(await world.install(), PackageInstalled)


class TestAnInstallThatFails:
    async def test_no_boot_file_keeps_the_download_recorded_as_it_was(self, world):
        world.control.status = 0

        outcome = await world.install()

        assert outcome == PackageNotInstalled(NO_BOOT_FILE, "RPCS3")
        assert world.record().package_boot_file is None
        assert world.record().rom_dir == str(world.download)
        assert (world.download / "UP0001-NPUB30000_00-GAME.pkg").is_file()

    async def test_a_command_that_cannot_start_keeps_the_download(self, world):
        world.control.raises = FileNotFoundError("flatpak")

        assert await world.install() == PackageNotInstalled(NOT_STARTED, "RPCS3")
        assert world.download.is_dir()

    async def test_an_install_that_does_not_end_is_ended_and_keeps_the_download(self, world):
        world.control.hangs = True
        world.step._timeout_seconds = 0.05

        assert await world.install() == PackageNotInstalled(DID_NOT_FINISH, "RPCS3")
        assert world.control.cancelled
        assert world.download.is_dir()

    async def test_a_refused_install_runs_nothing(self, world):
        world.reader.answer = PackageInstallRefused(COMMAND_INCOMPLETE, "RPCS3")

        assert await world.install() == PackageNotInstalled(COMMAND_INCOMPLETE, "RPCS3")
        assert world.control.ran == []
        assert world.record().package_boot_file is None

    async def test_a_cancel_ends_the_install_and_keeps_the_download(self, world):
        world.control.hangs = True
        task = asyncio.ensure_future(world.install())
        await asyncio.sleep(0.05)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert world.control.cancelled
        assert world.record().package_boot_file is None
        assert world.download.is_dir()


class TestNothingToInstall:
    async def test_a_download_that_is_no_package_is_left_alone(self, world):
        world.reader.answer = None

        assert await world.install() is None
        assert world.control.ran == []

    async def test_a_title_already_installed_is_not_asked_about_again(self, world):
        world.control.effect = write_boot_file(world.title.boot_file)
        await world.install()
        world.reader.asked.clear()

        assert await world.install() is None
        assert world.reader.asked == []

    async def test_a_game_with_no_record_is_left_alone(self, world):
        world.uow.rom_installs.delete(7)

        assert await world.install() is None
