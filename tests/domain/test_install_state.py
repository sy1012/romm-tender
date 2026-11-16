from __future__ import annotations

from domain.install_state import installed_shortcut_app_ids
from domain.rom import Rom


def _rom(rom_id: int, app_id: int | None, group: str | None = None) -> Rom:
    return Rom(
        rom_id=rom_id,
        platform_slug="snes",
        name=f"Game {rom_id}",
        fs_name=f"game_{rom_id}.sfc",
        shortcut_app_id=app_id,
        last_synced_at="2025-01-01T00:00:00",
        sibling_group_key=group,
    )


def test_a_shortcut_whose_own_rom_is_present_is_installed():
    assert installed_shortcut_app_ids([_rom(1, 101), _rom(2, 102)], {1}) == [101]


def test_a_shortcut_is_installed_when_any_version_in_its_group_is_present():
    roms = [_rom(1, 101, "mario"), _rom(2, None, "mario"), _rom(3, 103, "zelda")]

    assert installed_shortcut_app_ids(roms, {2}) == [101]


def test_every_shortcut_a_group_still_has_counts_once_any_member_is_present():
    roms = [_rom(1, 101, "mario"), _rom(2, 102, "mario")]

    assert installed_shortcut_app_ids(roms, {2}) == [101, 102]


def test_a_rom_with_no_group_answers_for_itself_alone():
    roms = [_rom(1, 101), _rom(2, 102)]

    assert installed_shortcut_app_ids(roms, {2}) == [102]


def test_nothing_present_is_nothing_installed():
    assert installed_shortcut_app_ids([_rom(1, 101, "mario")], set()) == []
