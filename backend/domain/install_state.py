"""Which of Tender's shortcuts Steam is told are installed.

A shortcut stands for a sibling group of versions, so it counts as installed
when any version in its group is present on this device — the shortcut can
start something. What "present" means is the caller's: an install record whose
file or folder still exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence, Set

    from domain.rom import Rom


def installed_shortcut_app_ids(roms: Sequence[Rom], present_rom_ids: Set[int]) -> list[int]:
    """The shortcut appIds, ascending, whose own ROM or any ROM of whose group is in *present_rom_ids*."""
    present_groups = {
        rom.sibling_group_key for rom in roms if rom.rom_id in present_rom_ids and rom.sibling_group_key is not None
    }
    return sorted(
        {
            rom.shortcut_app_id
            for rom in roms
            if rom.shortcut_app_id is not None
            and (rom.rom_id in present_rom_ids or rom.sibling_group_key in present_groups)
        }
    )
