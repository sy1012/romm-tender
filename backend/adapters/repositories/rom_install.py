"""SQLite adapter for the ``RomInstall`` aggregate over the ``rom_installs`` table and its extra content's rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from adapters.repositories._base import BaseRepository
from domain.rom_install import InstalledExtraContent, RomInstall

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator

_COLUMNS = "rom_id, file_path, rom_dir, platform_slug, system, installed_at, fetched_size_bytes, package_boot_file"


def _row_to_install(row: sqlite3.Row, extra_content: tuple[InstalledExtraContent, ...]) -> RomInstall:
    return RomInstall(
        rom_id=row["rom_id"],
        file_path=row["file_path"],
        rom_dir=row["rom_dir"],
        platform_slug=row["platform_slug"],
        system=row["system"],
        installed_at=row["installed_at"],
        fetched_size_bytes=row["fetched_size_bytes"],
        extra_content=extra_content,
        package_boot_file=row["package_boot_file"],
    )


class SqliteRomInstallRepository(BaseRepository):
    """Install records — present only while a ROM is downloaded; ``rom_dir`` is NULL for single-file ROMs.

    An install's extra content lives in ``rom_install_extra_content`` and is
    written and dropped with its ``rom_installs`` row, never apart from it.
    """

    def get(self, rom_id: int) -> RomInstall | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM rom_installs WHERE rom_id = ?",
            (rom_id,),
        ).fetchone()
        return _row_to_install(row, self._extra_content(rom_id)) if row is not None else None

    def save(self, install: RomInstall) -> None:
        self._conn.execute(
            f"INSERT OR REPLACE INTO rom_installs ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                install.rom_id,
                install.file_path,
                install.rom_dir,
                install.platform_slug,
                install.system,
                install.installed_at,
                install.fetched_size_bytes,
                install.package_boot_file,
            ),
        )
        self._conn.execute("DELETE FROM rom_install_extra_content WHERE rom_id = ?", (install.rom_id,))
        self._conn.executemany(
            "INSERT INTO rom_install_extra_content (rom_id, file_id, rel_path, size_bytes) VALUES (?, ?, ?, ?)",
            [(install.rom_id, e.file_id, e.rel_path, e.size_bytes) for e in install.extra_content],
        )

    def delete(self, rom_id: int) -> None:
        self._conn.execute("DELETE FROM rom_install_extra_content WHERE rom_id = ?", (rom_id,))
        self._conn.execute("DELETE FROM rom_installs WHERE rom_id = ?", (rom_id,))

    def iter_all(self) -> Iterator[RomInstall]:
        rows = self._conn.execute(f"SELECT {_COLUMNS} FROM rom_installs").fetchall()
        for row in rows:
            yield _row_to_install(row, self._extra_content(row["rom_id"]))

    def _extra_content(self, rom_id: int) -> tuple[InstalledExtraContent, ...]:
        return tuple(
            InstalledExtraContent(file_id=r["file_id"], rel_path=r["rel_path"], size_bytes=r["size_bytes"])
            for r in self._conn.execute(
                "SELECT file_id, rel_path, size_bytes FROM rom_install_extra_content WHERE rom_id = ? ORDER BY file_id",
                (rom_id,),
            )
        )
