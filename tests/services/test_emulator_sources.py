"""Tests for services/emulator_sources.py — the settings list, the switch and the order.

The service runs over the real sources holder with a detection the test names,
so "kept" means what the user sees: the next reading arranges the sources the
way the stored settings say.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from _vendor.atlas import (
    AVAILABILITY_NOT_INSTALLED,
    AVAILABILITY_STARTABLE,
    CAVEAT_EMULATOR_CATALOGUE_SEALED,
    HEALTH_ISSUE_ROOT_MISSING,
)
from _vendor.atlas.installations import Health, SystemsAnswer
from _vendor.atlas.placement import Caveat
from fakes.fake_settings_persister import FakeSettingsPersister
from fakes.fake_unit_of_work import FakeUnitOfWorkFactory
from fakes.running_loop import running_loop

from adapters.emulator_sources import EmulatorSourcesAdapter
from domain.refusal import DomainRefused
from domain.rom import Rom
from domain.rom_install import RomInstall
from lib.errors import Refused
from services.emulator_sources import EmulatorSourcesService, EmulatorSourcesServiceConfig


class _Installation:
    """A source; *startable* and *not_installed* name the systems it holds an entry for, and whether it starts."""

    def __init__(
        self,
        kind: str,
        *,
        issues: tuple[Caveat, ...] = (),
        sealed: bool = False,
        startable: tuple[str, ...] = (),
        not_installed: tuple[str, ...] = (),
    ) -> None:
        self.kind = kind
        self._issues = issues
        self._sealed = sealed
        self._startable = startable
        self._not_installed = not_installed

    def emulators_for(self, system: str, *, content_path: str | None = None) -> Any:
        availability = (
            AVAILABILITY_STARTABLE
            if system in self._startable
            else AVAILABILITY_NOT_INSTALLED
            if system in self._not_installed
            else None
        )
        entries = () if availability is None else (SimpleNamespace(availability=availability),)
        return SimpleNamespace(entries=entries, caveats=())

    def health(self) -> Health:
        return Health(self._issues)

    def root(self) -> str:
        return f"/roots/{self.kind}"

    def systems(self) -> SystemsAnswer:
        caveats = (Caveat(CAVEAT_EMULATOR_CATALOGUE_SEALED, "prose"),) if self._sealed else ()
        return SystemsAnswer(systems=("gba",), caveats=caveats)


class _Rig:
    def __init__(self, *installations: _Installation) -> None:
        self.detected = list(installations)
        self.settings: dict[str, Any] = {"emulator_source_order": [], "emulator_sources_off": []}
        self.persister = FakeSettingsPersister()
        self.uow_factory = FakeUnitOfWorkFactory()
        self.sources = EmulatorSourcesAdapter(
            user_home="/home/deck",
            settings=self.settings,
            log_debug=lambda message: None,
            detect_installations=lambda home, machine: list(self.detected),
            machine=object(),
        )
        self.service = EmulatorSourcesService(
            config=EmulatorSourcesServiceConfig(
                sources=self.sources,
                settings=self.settings,
                settings_persister=self.persister,
                uow_factory=self.uow_factory,
                loop=running_loop(),
                log_debug=lambda msg: None,
            )
        )

    def kinds(self, listing: dict[str, Any]) -> list[str]:
        return [source["kind"] for source in listing["sources"]]

    def install(self, rom_id: int, system: str) -> None:
        self.uow_factory.uow.roms.save(
            Rom.synced(
                rom_id=rom_id,
                platform_slug=system,
                name=f"Game {rom_id}",
                fs_name=f"game-{rom_id}",
                shortcut_app_id=None,
                synced_at="2026-11-17T00:00:00",
            )
        )
        self.uow_factory.uow.rom_installs.save(
            RomInstall(
                rom_id=rom_id,
                file_path=f"/roms/{system}/game",
                rom_dir=None,
                platform_slug=system,
                system=system,
                installed_at="2026-11-17T00:00:00Z",
            )
        )


@pytest.fixture
def both() -> _Rig:
    return _Rig(
        _Installation("retrodeck", issues=(Caveat(HEALTH_ISSUE_ROOT_MISSING, "prose", {"path": "/sd/retrodeck"}),)),
        _Installation("emudeck", sealed=True),
    )


class TestTheListing:
    @pytest.mark.asyncio
    async def test_retrodeck_and_emudeck_are_listed_with_their_health_and_switch(self, both):
        listing = await both.service.get_emulator_sources()

        assert listing == {
            "sources": [
                {
                    "kind": "retrodeck",
                    "enabled": True,
                    "starts_games": True,
                    "root": "/roots/retrodeck",
                    "findings": [{"code": HEALTH_ISSUE_ROOT_MISSING, "data": {"path": "/sd/retrodeck"}}],
                    "catalogue": "read",
                },
                {
                    "kind": "emudeck",
                    "enabled": True,
                    "starts_games": False,
                    "root": "/roots/emudeck",
                    "findings": [],
                    "catalogue": "sealed",
                },
            ],
            "answering": "retrodeck",
        }

    @pytest.mark.asyncio
    async def test_nothing_detected_lists_nothing(self):
        assert await _Rig().service.get_emulator_sources() == {"sources": [], "answering": None}

    @pytest.mark.asyncio
    async def test_with_retrodeck_switched_off_emudeck_answers(self, both):
        listing = await both.service.set_emulator_source_enabled("retrodeck", False)

        assert listing["answering"] == "emudeck"


class TestTheStartCheck:
    @pytest.mark.asyncio
    async def test_retrodeck_switched_off_is_named_as_the_source_a_start_is_refused_for(self, both):
        await both.service.set_emulator_source_enabled("retrodeck", False)

        assert await both.service.check_start_source() == {"switched_off": "retrodeck"}

    @pytest.mark.asyncio
    async def test_switched_on_again_it_refuses_nothing(self, both):
        await both.service.set_emulator_source_enabled("retrodeck", False)
        await both.service.set_emulator_source_enabled("retrodeck", True)

        assert await both.service.check_start_source() == {"switched_off": None}

    @pytest.mark.asyncio
    async def test_a_retrodeck_no_longer_detected_refuses_nothing(self, both):
        await both.service.set_emulator_source_enabled("retrodeck", False)
        both.detected = [installation for installation in both.detected if installation.kind != "retrodeck"]

        assert await both.service.check_start_source() == {"switched_off": None}

    @pytest.mark.asyncio
    async def test_a_detection_that_raised_is_refused_never_read_as_no_source(self, both):
        def explode(home: str, machine: object) -> list[Any]:
            raise RuntimeError("resolver blew up")

        both.settings["emulator_sources_off"] = ["retrodeck"]
        both.sources._detect = explode

        with pytest.raises(Refused) as refusal:
            await both.service.check_start_source()

        assert refusal.value.reason == "detection_failed"

    @pytest.mark.asyncio
    async def test_it_detects_once_and_reads_nothing_else_of_a_source(self):
        asked: list[str] = []
        rig = _Rig(_Watched("retrodeck", asked), _Watched("emudeck", asked))
        rig.settings["emulator_sources_off"] = ["retrodeck"]
        detections: list[int] = []
        detect = rig.sources._detect
        rig.sources._detect = lambda home, machine: detections.append(1) or detect(home, machine)

        assert await rig.service.check_start_source() == {"switched_off": "retrodeck"}
        assert detections == [1]
        assert asked == []


@pytest.fixture
def with_eden() -> _Rig:
    rig = _Rig(
        _Installation("retrodeck", startable=("snes",), not_installed=("switch",)),
        _Installation("eden_appimage", startable=("switch",)),
    )
    rig.install(1, "switch")
    rig.install(2, "snes")
    return rig


class TestTheStartCheckForAGame:
    @pytest.mark.asyncio
    async def test_a_switched_off_eden_refuses_a_switch_game(self, with_eden):
        await with_eden.service.set_emulator_source_enabled("eden_appimage", False)

        assert await with_eden.service.check_start_source(1) == {"switched_off": "eden_appimage"}

    @pytest.mark.asyncio
    async def test_a_switched_off_eden_refuses_no_game_retrodeck_starts(self, with_eden):
        await with_eden.service.set_emulator_source_enabled("eden_appimage", False)

        assert await with_eden.service.check_start_source(2) == {"switched_off": None}

    @pytest.mark.asyncio
    async def test_a_switched_off_retrodeck_refuses_its_game_and_not_edens(self, with_eden):
        await with_eden.service.set_emulator_source_enabled("retrodeck", False)

        assert await with_eden.service.check_start_source(2) == {"switched_off": "retrodeck"}
        assert await with_eden.service.check_start_source(1) == {"switched_off": None}

    @pytest.mark.asyncio
    async def test_a_game_with_no_install_is_checked_for_no_system(self, with_eden):
        await with_eden.service.set_emulator_source_enabled("eden_appimage", False)

        assert await with_eden.service.check_start_source(99) == {"switched_off": None}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rom_id", ["1", 0, -3, 1.0, True])
    async def test_a_rom_id_that_is_not_a_positive_whole_number_is_refused(self, with_eden, rom_id):
        with pytest.raises(Refused) as refusal:
            await with_eden.service.check_start_source(rom_id)

        assert refusal.value.reason == "invalid_value"


class _Watched(_Installation):
    """A source that records every question put to it beyond its detection."""

    def __init__(self, kind: str, asked: list[str]) -> None:
        super().__init__(kind)
        self._asked = asked

    def health(self) -> Health:
        self._asked.append(f"{self.kind}.health")
        return super().health()

    def root(self) -> str:
        self._asked.append(f"{self.kind}.root")
        return super().root()

    def systems(self) -> SystemsAnswer:
        self._asked.append(f"{self.kind}.systems")
        return super().systems()


class TestTheSwitch:
    @pytest.mark.asyncio
    async def test_switching_a_source_off_stores_it_and_answers_the_new_listing(self, both):
        listing = await both.service.set_emulator_source_enabled("emudeck", False)

        assert both.settings["emulator_sources_off"] == ["emudeck"]
        assert both.persister.save_count == 1
        assert [source["enabled"] for source in listing["sources"]] == [True, False]

    @pytest.mark.asyncio
    async def test_switching_it_on_again_takes_it_off_the_list(self, both):
        await both.service.set_emulator_source_enabled("emudeck", False)
        listing = await both.service.set_emulator_source_enabled("emudeck", True)

        assert both.settings["emulator_sources_off"] == []
        assert [source["enabled"] for source in listing["sources"]] == [True, True]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("value", ["false", 0, None])
    async def test_a_switch_value_that_is_not_a_boolean_is_refused(self, both, value):
        with pytest.raises(Refused) as refusal:
            await both.service.set_emulator_source_enabled("emudeck", value)

        assert refusal.value.reason == "invalid_value"
        assert both.persister.save_count == 0

    @pytest.mark.asyncio
    async def test_a_source_that_is_not_detected_has_no_switch(self, both):
        with pytest.raises(DomainRefused) as refusal:
            await both.service.set_emulator_source_enabled("bare_retroarch_native", False)

        assert refusal.value.reason == "unknown_source"
        assert both.persister.save_count == 0
        assert both.settings["emulator_sources_off"] == []


class TestOneDetectionPerWrite:
    @pytest.mark.asyncio
    async def test_a_switch_detects_once(self, both):
        detections: list[int] = []
        detect = both.sources._detect
        both.sources._detect = lambda home, machine: detections.append(1) or detect(home, machine)

        listing = await both.service.set_emulator_source_enabled("emudeck", False)

        assert detections == [1]
        assert [source["enabled"] for source in listing["sources"]] == [True, False]

    @pytest.mark.asyncio
    async def test_a_move_detects_once(self, both):
        detections: list[int] = []
        detect = both.sources._detect
        both.sources._detect = lambda home, machine: detections.append(1) or detect(home, machine)

        listing = await both.service.move_emulator_source("emudeck", "up")

        assert detections == [1]
        assert both.kinds(listing) == ["emudeck", "retrodeck"]


class TestTheOrder:
    @pytest.mark.asyncio
    async def test_a_move_is_stored_and_kept_for_the_next_reading(self, both):
        listing = await both.service.move_emulator_source("emudeck", "up")

        assert both.settings["emulator_source_order"] == ["emudeck", "retrodeck"]
        assert both.persister.save_count == 1
        assert both.kinds(listing) == ["emudeck", "retrodeck"]
        assert both.kinds(await both.service.get_emulator_sources()) == ["emudeck", "retrodeck"]
        assert both.sources.read().answering_kind == "retrodeck"

    @pytest.mark.asyncio
    async def test_moving_down_moves_it_back(self, both):
        await both.service.move_emulator_source("emudeck", "up")
        listing = await both.service.move_emulator_source("emudeck", "down")

        assert both.kinds(listing) == ["retrodeck", "emudeck"]

    @pytest.mark.asyncio
    async def test_a_move_past_the_end_is_refused_and_stores_nothing(self, both):
        with pytest.raises(DomainRefused) as refusal:
            await both.service.move_emulator_source("retrodeck", "up")

        assert refusal.value.reason == "cannot_move"
        assert both.persister.save_count == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("direction", ["left", "", "UP"])
    async def test_a_direction_that_is_not_up_or_down_is_refused(self, both, direction):
        with pytest.raises(Refused) as refusal:
            await both.service.move_emulator_source("emudeck", direction)

        assert refusal.value.reason == "invalid_direction"
        assert both.persister.save_count == 0
