"""RomInstall — the on-disk install record for a downloaded ROM.

Exists only while a ROM is downloaded: created on download-complete, removed on
uninstall. References its Rom by ``rom_id``. Always carries the specific launch
``file_path``; ``rom_dir`` names the dedicated per-ROM directory and is set for
every game that lands in a folder of its own (a game RomM holds as a folder,
whatever a download fetches of it, or a single zip unpacked into a folder) — it
is ``None`` only for a game RomM holds as one file, kept as it arrived, which
lives as a bare file in the shared system directory and owns no folder. The
denormalized ``platform_slug``/``system`` let the home migration and the save
answer read this record without joining the registry. Whether that launch file
starts is not recorded: it is the resolver's answer, asked when it is read.
The game's extra content downloaded into its folder is recorded with it
(``extra_content``), each file by its place inside ``rom_dir``; whether the
game is installed does not depend on it. A game installed into its emulator
from a package (ADR-0051) records the installed title instead of the download:
``rom_dir`` is the title's folder on the emulator's drive, ``file_path`` its
boot file, and ``package_boot_file`` the boot file as the emulator spells it,
which is set for such a game alone and is what says it was installed so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain._aggregate import cosmic_aggregate

if TYPE_CHECKING:
    from domain.package_install import InstalledTitle


@dataclass(frozen=True, slots=True)
class InstalledExtraContent:
    """One file of a game's extra content on this device.

    RomM's id for it, where it lies inside the game's folder, and RomM's size of it.
    """

    file_id: int
    rel_path: str
    size_bytes: int


@cosmic_aggregate
class RomInstall:
    """Where a downloaded ROM lives on disk and which file launches it."""

    rom_id: int
    file_path: str
    rom_dir: str | None
    platform_slug: str
    system: str
    installed_at: str
    fetched_size_bytes: int | None = None
    extra_content: tuple[InstalledExtraContent, ...] = ()
    package_boot_file: str | None = None

    @classmethod
    def mark_installed(
        cls,
        *,
        rom_id: int,
        file_path: str,
        rom_dir: str | None,
        platform_slug: str,
        system: str,
        installed_at: str,
        fetched_size_bytes: int | None = None,
    ) -> RomInstall:
        """Record a freshly downloaded ROM installed at ISO timestamp ``installed_at``.

        ``rom_dir`` is the dedicated per-ROM directory of a game that lands in a
        folder of its own, or ``None`` for a game RomM holds as one file, kept
        as it arrived. ``fetched_size_bytes`` is RomM's size of the files a
        download of the game fetches (an adoption records the same figure),
        ``None`` where it states none; a size of zero or less states nothing and
        raises ``ValueError``.
        """
        if rom_id <= 0:
            raise ValueError("rom_id must be positive")
        if fetched_size_bytes is not None and fetched_size_bytes <= 0:
            raise ValueError("fetched_size_bytes must be positive")
        return cls(
            rom_id=rom_id,
            file_path=file_path,
            rom_dir=rom_dir,
            platform_slug=platform_slug,
            system=system,
            installed_at=installed_at,
            fetched_size_bytes=fetched_size_bytes,
        )

    def relocate(self, new_rom_dir: str | None, new_file_path: str) -> None:
        """Move the install to a new launch file and per-ROM directory.

        ``new_rom_dir`` stays ``None`` for a single-file ROM; a folder-backed
        ROM carries its relocated dedicated directory.
        """
        self.rom_dir = new_rom_dir
        self.file_path = new_file_path

    def install_from_package(self, title: InstalledTitle) -> None:
        """Record the game as the title a package install of its download left in the emulator's drive.

        The download goes once this is recorded, and its extra content with it:
        the same install took every package of it into the emulator.
        """
        self.rom_dir = title.folder
        self.file_path = title.boot_file
        self.package_boot_file = title.boot_file_in_emulator
        self.extra_content = ()

    def add_extra_content(self, file_id: int, rel_path: str, size_bytes: int) -> None:
        """Record a file of the game's extra content downloaded to *rel_path* inside the game's folder.

        A game with no folder of its own keeps none, and a *rel_path* that is
        empty names no place: both raise ``ValueError``. A file already recorded
        under *file_id* is recorded again at its new place.
        """
        if self.rom_dir is None:
            raise ValueError("a game kept as one file keeps no extra content")
        if self.package_boot_file is not None:
            raise ValueError("a game installed from a package keeps its extra content in the emulator")
        if not rel_path:
            raise ValueError("extra content needs a place inside the game's folder")
        kept = tuple(entry for entry in self.extra_content if entry.file_id != file_id)
        self.extra_content = (*kept, InstalledExtraContent(file_id, rel_path, max(int(size_bytes), 0)))

    def remove_extra_content(self, file_id: int) -> None:
        """Forget the file of extra content recorded under *file_id*; one not recorded changes nothing."""
        self.extra_content = tuple(entry for entry in self.extra_content if entry.file_id != file_id)

    @property
    def extra_content_bytes(self) -> int:
        """RomM's size of the extra content recorded on this device."""
        return sum(entry.size_bytes for entry in self.extra_content)
