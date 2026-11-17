"""Contract: the emulator sources endpoints over the real bootstrap and the real resolver.

The harness's home holds a seeded RetroDECK and nothing else, so what is
listed, switched and answered here is what the real holder detects under it.
"""

from __future__ import annotations

import os

from ._seed import _retrodeck_marker_path, seed_es_systems, seed_install, seed_retrodeck_not_set_up, seed_rom


def _seed_eden_appimage(harness, name: str = "Eden-Linux-amd64.AppImage") -> str:
    """An Eden AppImage in ``~/Applications`` under the harness ``user_home``; its path."""
    folder = os.path.join(str(harness.tmp_path), "home", "Applications")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as handle:
        handle.write(b"\x7fELF")
    return path


async def test_the_listing_names_a_detected_retrodeck(harness):
    seed_es_systems(harness)

    result = await harness.endpoints.get_emulator_sources()

    assert set(result) == {"sources", "answering"}
    assert result["answering"] == "retrodeck"
    (source,) = result["sources"]
    assert set(source) == {"kind", "enabled", "starts_games", "root", "findings", "catalogue"}
    assert (source["kind"], source["enabled"], source["starts_games"], source["catalogue"]) == (
        "retrodeck",
        True,
        True,
        "read",
    )


async def test_nothing_detected_lists_nothing(harness):
    assert await harness.endpoints.get_emulator_sources() == {"sources": [], "answering": None}


async def test_switching_the_source_off_takes_its_emulators_away_and_on_brings_them_back(harness):
    seed_es_systems(harness)
    assert (await harness.endpoints.get_system_core_info("gba", "gba"))["emulator_data_available"] is True

    await harness.endpoints.set_emulator_source_enabled("retrodeck", False)
    off = await harness.endpoints.get_system_core_info("gba", "gba")
    await harness.endpoints.set_emulator_source_enabled("retrodeck", True)
    on = await harness.endpoints.get_system_core_info("gba", "gba")

    assert (off["emulator_data_available"], off["emulators"], off["emulator_data_reason"]) == (
        False,
        [],
        "switched_off",
    )
    assert harness.settings["emulator_sources_off"] == []
    assert on["emulator_data_available"] is True
    assert on["emulators"] != []


async def test_a_game_s_emulators_follow_the_source_switched_off_and_on(harness):
    seed_es_systems(harness)
    seed_rom(harness, 42, platform_slug="gba")
    before = await harness.endpoints.get_platform_core_info(42)

    await harness.endpoints.set_emulator_source_enabled("retrodeck", False)
    off = await harness.endpoints.get_platform_core_info(42)
    await harness.endpoints.set_emulator_source_enabled("retrodeck", True)
    on = await harness.endpoints.get_platform_core_info(42)

    assert (off["emulator_data_available"], off["emulators"], off["emulator_data_reason"]) == (
        False,
        [],
        "switched_off",
    )
    assert off["active_core_label"] is None
    assert on == before
    assert on["emulator_data_available"] is True
    assert on["active_core_label"] == "mGBA"


async def test_a_source_that_is_not_detected_is_refused_in_the_failure_shape(harness):
    seed_es_systems(harness)

    result = await harness.endpoints.move_emulator_source("emudeck", "up")

    assert result["success"] is False
    assert result["reason"] == "unknown_source"
    assert isinstance(result["message"], str)


async def test_a_malformed_retrodeck_json_is_listed_with_its_finding(harness):
    seed_es_systems(harness)
    with open(_retrodeck_marker_path(harness), "w") as handle:
        handle.write("{not json")

    (source,) = (await harness.endpoints.get_emulator_sources())["sources"]

    assert source["kind"] == "retrodeck"
    assert "marker-invalid" in {finding["code"] for finding in source["findings"]}
    assert source["root"] is None


async def test_a_retrodeck_that_is_not_set_up_is_listed_and_answers_why_it_has_no_emulator_list(harness):
    seed_retrodeck_not_set_up(harness)

    listing = await harness.endpoints.get_emulator_sources()
    info = await harness.endpoints.get_system_core_info("gba", "gba")

    assert listing["answering"] == "retrodeck"
    (source,) = listing["sources"]
    assert [finding["code"] for finding in source["findings"]] == ["not-set-up"]
    assert (source["enabled"], source["root"], source["catalogue"]) == (True, None, "unavailable")
    assert (info["emulator_data_available"], info["emulators"], info["emulator_data_reason"]) == (
        False,
        [],
        "not_set_up",
    )
    assert info["emulator_source"] == {"kind": "retrodeck", "starts_games": True}


async def test_the_start_check_names_retrodeck_while_it_is_switched_off(harness):
    seed_es_systems(harness)
    on = await harness.endpoints.check_start_source()

    await harness.endpoints.set_emulator_source_enabled("retrodeck", False)
    off = await harness.endpoints.check_start_source()
    await harness.endpoints.set_emulator_source_enabled("retrodeck", True)

    assert on == {"switched_off": None}
    assert off == {"switched_off": "retrodeck"}
    assert await harness.endpoints.check_start_source() == {"switched_off": None}


async def test_the_start_check_refuses_nothing_where_no_retrodeck_is_detected(harness):
    harness.settings["emulator_sources_off"] = ["retrodeck"]

    assert await harness.endpoints.check_start_source() == {"switched_off": None}


async def test_the_start_check_answers_a_failed_detection_in_the_failure_shape(harness):
    seed_es_systems(harness)

    def explode(home, machine):
        raise RuntimeError("resolver blew up")

    harness.app.services.emulator_sources_service._sources._detect = explode
    result = await harness.endpoints.check_start_source()

    assert result["success"] is False
    assert result["reason"] == "detection_failed"
    assert isinstance(result["message"], str)


async def test_an_eden_appimage_is_listed_as_a_source_that_starts_games_after_retrodeck(harness):
    seed_es_systems(harness)
    _seed_eden_appimage(harness)

    listing = await harness.endpoints.get_emulator_sources()

    assert [(source["kind"], source["starts_games"]) for source in listing["sources"]] == [
        ("retrodeck", True),
        ("eden_appimage", True),
    ]
    assert listing["answering"] == "retrodeck"


async def test_a_switched_off_eden_refuses_its_switch_game_and_no_other(harness):
    seed_es_systems(harness)
    _seed_eden_appimage(harness)
    seed_install(harness, 7, system="switch", platform_slug="switch", file_name="Zelda [01007EF00011E000].nsp")
    seed_install(harness, 8)

    await harness.endpoints.set_emulator_source_enabled("eden_appimage", False)

    assert await harness.endpoints.check_start_source(7) == {"switched_off": "eden_appimage"}
    assert await harness.endpoints.check_start_source(8) == {"switched_off": None}


async def test_a_rom_id_that_is_no_game_is_refused_in_the_failure_shape(harness):
    result = await harness.endpoints.check_start_source("seven")

    assert result["success"] is False
    assert result["reason"] == "invalid_value"


async def test_several_eden_appimages_are_a_finding_until_one_is_named(harness):
    first = _seed_eden_appimage(harness, "Eden-stable.AppImage")
    _seed_eden_appimage(harness, "eden-nightly.AppImage")

    (several,) = (await harness.endpoints.get_emulator_sources())["sources"]
    saved = harness.endpoints.save_eden_appimage(first)
    (named,) = (await harness.endpoints.get_emulator_sources())["sources"]

    assert [finding["code"] for finding in several["findings"]] == ["several-appimages"]
    assert saved == {"success": True}
    assert harness.settings["eden_appimage"] == first
    assert named["findings"] == []


async def test_a_named_eden_appimage_that_is_not_there_is_listed_with_its_finding(harness):
    missing = os.path.join(str(harness.tmp_path), "nowhere", "Eden.AppImage")

    harness.endpoints.save_eden_appimage(missing)
    (source,) = (await harness.endpoints.get_emulator_sources())["sources"]

    assert source["kind"] == "eden_appimage"
    assert [finding["code"] for finding in source["findings"]] == ["marker-missing"]


async def test_a_relative_eden_appimage_is_refused_in_the_failure_shape(harness):
    result = harness.endpoints.save_eden_appimage("Applications/Eden.AppImage")

    assert result["success"] is False
    assert result["reason"] == "invalid_value"
    assert isinstance(result["message"], str)
    assert harness.settings.get("eden_appimage", "") == ""
