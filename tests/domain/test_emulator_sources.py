"""Tests for domain/emulator_sources.py — order, switches and the answering source."""

from __future__ import annotations

import pytest

from domain.emulator_sources import (
    ALL_SOURCES_SWITCHED_OFF,
    NO_SOURCE_DETECTED,
    ArrangedSource,
    SystemListing,
    answering_source,
    answering_source_for,
    arrange_sources,
    is_absolute_path,
    move_source,
    no_answering_source_reason,
    switch_source,
    switched_off_starting_source,
)
from domain.refusal import DomainRefused

PROBE_ORDER = ("retrodeck", "emudeck", "bare_retroarch_flatpak", "bare_retroarch_native")


def _kinds(sources: tuple[ArrangedSource, ...]) -> list[str]:
    return [source.kind for source in sources]


class TestArrangeSources:
    def test_with_nothing_stored_the_order_is_the_probe_order(self):
        sources = arrange_sources(detected=PROBE_ORDER, stored_order=(), switched_off=())
        assert _kinds(sources) == list(PROBE_ORDER)

    def test_a_stored_order_ranks_the_kinds_it_names(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"), stored_order=("emudeck", "retrodeck"), switched_off=()
        )
        assert _kinds(sources) == ["emudeck", "retrodeck"]

    def test_a_kind_seen_for_the_first_time_joins_at_the_end_switched_on(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck", "bare_retroarch_native"),
            stored_order=("emudeck", "retrodeck"),
            switched_off=(),
        )
        assert _kinds(sources) == ["emudeck", "retrodeck", "bare_retroarch_native"]
        assert sources[-1].enabled is True

    def test_a_kind_unknown_to_tender_is_listed_like_any_other(self):
        sources = arrange_sources(detected=("retrodeck", "standalone_x"), stored_order=(), switched_off=())
        assert _kinds(sources) == ["retrodeck", "standalone_x"]

    def test_a_stored_kind_that_is_not_detected_is_not_listed(self):
        sources = arrange_sources(detected=("emudeck",), stored_order=("retrodeck", "emudeck"), switched_off=())
        assert _kinds(sources) == ["emudeck"]

    def test_a_duplicate_in_the_stored_order_lists_the_kind_once(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"), stored_order=("emudeck", "emudeck", "retrodeck"), switched_off=()
        )
        assert _kinds(sources) == ["emudeck", "retrodeck"]

    def test_a_switched_off_kind_is_listed_disabled(self):
        sources = arrange_sources(detected=("retrodeck", "emudeck"), stored_order=(), switched_off=("emudeck",))
        assert [(source.kind, source.enabled) for source in sources] == [("retrodeck", True), ("emudeck", False)]

    def test_only_retrodeck_starts_games(self):
        sources = arrange_sources(detected=PROBE_ORDER, stored_order=(), switched_off=())
        assert [source.starts_games for source in sources] == [True, False, False, False]

    def test_nothing_detected_lists_nothing(self):
        assert arrange_sources(detected=(), stored_order=("retrodeck",), switched_off=()) == ()


class TestAnsweringSource:
    def test_retrodeck_answers_even_when_another_source_is_first_in_the_order(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"), stored_order=("emudeck", "retrodeck"), switched_off=()
        )
        chosen = answering_source(sources)
        assert chosen is not None
        assert chosen.kind == "retrodeck"
        assert chosen.starts_games is True

    def test_without_retrodeck_the_first_enabled_source_answers_and_cannot_start_games(self):
        sources = arrange_sources(detected=("emudeck",), stored_order=(), switched_off=())
        chosen = answering_source(sources)
        assert chosen is not None
        assert chosen.kind == "emudeck"
        assert chosen.starts_games is False

    def test_retrodeck_switched_off_hands_the_answer_to_the_first_enabled_source(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck", "bare_retroarch_native"),
            stored_order=("bare_retroarch_native", "emudeck", "retrodeck"),
            switched_off=("retrodeck",),
        )
        chosen = answering_source(sources)
        assert chosen is not None
        assert chosen.kind == "bare_retroarch_native"

    def test_a_switched_off_source_is_skipped(self):
        sources = arrange_sources(
            detected=("emudeck", "bare_retroarch_native"), stored_order=(), switched_off=("emudeck",)
        )
        chosen = answering_source(sources)
        assert chosen is not None
        assert chosen.kind == "bare_retroarch_native"

    def test_nothing_detected_answers_none_with_its_reason(self):
        assert answering_source(()) is None
        assert no_answering_source_reason(()) == NO_SOURCE_DETECTED

    def test_everything_switched_off_answers_none_with_its_reason(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"), stored_order=(), switched_off=("retrodeck", "emudeck")
        )
        assert answering_source(sources) is None
        assert no_answering_source_reason(sources) == ALL_SOURCES_SWITCHED_OFF


class TestSwitchedOffStartingSource:
    def test_retrodeck_switched_off_refuses_a_start_by_naming_it(self):
        sources = arrange_sources(detected=("retrodeck",), stored_order=(), switched_off=("retrodeck",))
        assert switched_off_starting_source(sources) == "retrodeck"

    def test_a_switched_on_source_that_cannot_start_games_does_not_lift_the_refusal(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"), stored_order=("emudeck", "retrodeck"), switched_off=("retrodeck",)
        )
        assert switched_off_starting_source(sources) == "retrodeck"

    def test_retrodeck_switched_on_refuses_nothing(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"), stored_order=("emudeck", "retrodeck"), switched_off=("emudeck",)
        )
        assert switched_off_starting_source(sources) is None

    def test_retrodeck_not_detected_refuses_nothing_even_when_stored_as_switched_off(self):
        sources = arrange_sources(detected=("emudeck",), stored_order=(), switched_off=("retrodeck",))
        assert switched_off_starting_source(sources) is None

    def test_nothing_detected_refuses_nothing(self):
        assert switched_off_starting_source(()) is None

    def test_a_switched_off_source_that_cannot_start_games_refuses_nothing(self):
        sources = arrange_sources(detected=("emudeck",), stored_order=(), switched_off=("emudeck",))
        assert switched_off_starting_source(sources) is None

    def test_the_starting_source_is_named_though_another_switched_off_source_comes_first(self):
        sources = arrange_sources(
            detected=("retrodeck", "emudeck"),
            stored_order=("emudeck", "retrodeck"),
            switched_off=("emudeck", "retrodeck"),
        )
        assert switched_off_starting_source(sources) == "retrodeck"

    def test_the_kind_named_is_that_of_the_source_that_would_start_the_game(self):
        sources = (
            ArrangedSource(kind="retrodeck", enabled=True, starts_games=False),
            ArrangedSource(kind="emudeck", enabled=False, starts_games=True),
        )
        assert switched_off_starting_source(sources) == "emudeck"

    def test_a_switched_on_source_that_starts_games_takes_over_from_a_switched_off_one(self):
        sources = (
            ArrangedSource(kind="emudeck", enabled=False, starts_games=True),
            ArrangedSource(kind="retrodeck", enabled=True, starts_games=True),
        )
        assert switched_off_starting_source(sources) is None


class TestMoveSource:
    def test_moving_down_swaps_with_the_next_source(self):
        order = move_source(kind="retrodeck", offset=1, detected=("retrodeck", "emudeck"), stored_order=())
        assert order == ("emudeck", "retrodeck")

    def test_moving_up_swaps_with_the_previous_source(self):
        order = move_source(kind="bare_retroarch_native", offset=-1, detected=PROBE_ORDER, stored_order=())
        assert order == ("retrodeck", "emudeck", "bare_retroarch_native", "bare_retroarch_flatpak")

    def test_a_move_skips_a_stored_kind_that_is_not_detected_and_keeps_its_place(self):
        order = move_source(
            kind="emudeck",
            offset=-1,
            detected=("retrodeck", "emudeck"),
            stored_order=("retrodeck", "bare_retroarch_native", "emudeck"),
        )
        assert order == ("emudeck", "bare_retroarch_native", "retrodeck")

    def test_a_move_past_the_top_is_refused(self):
        with pytest.raises(DomainRefused) as refusal:
            move_source(kind="retrodeck", offset=-1, detected=("retrodeck", "emudeck"), stored_order=())
        assert refusal.value.reason == "cannot_move"

    def test_a_move_past_the_bottom_is_refused(self):
        with pytest.raises(DomainRefused) as refusal:
            move_source(kind="emudeck", offset=1, detected=("retrodeck", "emudeck"), stored_order=())
        assert refusal.value.reason == "cannot_move"

    def test_moving_a_kind_that_is_not_detected_is_refused(self):
        with pytest.raises(DomainRefused) as refusal:
            move_source(kind="emudeck", offset=1, detected=("retrodeck",), stored_order=("emudeck",))
        assert refusal.value.reason == "unknown_source"

    @pytest.mark.parametrize("offset", [0, 2, -2])
    def test_an_offset_other_than_one_place_is_a_programming_error(self, offset):
        with pytest.raises(ValueError, match="one place at a time"):
            move_source(kind="retrodeck", offset=offset, detected=("retrodeck", "emudeck"), stored_order=())


class TestSwitchSource:
    def test_switching_off_adds_the_kind(self):
        assert switch_source(kind="emudeck", enabled=False, detected=("emudeck",), switched_off=()) == ("emudeck",)

    def test_switching_on_removes_the_kind(self):
        assert switch_source(
            kind="emudeck", enabled=True, detected=("emudeck",), switched_off=("retrodeck", "emudeck")
        ) == ("retrodeck",)

    def test_switching_off_twice_lists_the_kind_once(self):
        assert switch_source(kind="emudeck", enabled=False, detected=("emudeck",), switched_off=("emudeck",)) == (
            "emudeck",
        )

    def test_switching_a_kind_that_is_not_detected_is_refused(self):
        with pytest.raises(DomainRefused) as refusal:
            switch_source(kind="emudeck", enabled=False, detected=("retrodeck",), switched_off=())
        assert refusal.value.reason == "unknown_source"


def _source(kind: str, *, enabled: bool = True) -> ArrangedSource:
    return arrange_sources(detected=(kind,), stored_order=(), switched_off=() if enabled else (kind,))[0]


def _kind(source: ArrangedSource | None) -> str | None:
    return source.kind if source is not None else None


def _listing(table: dict[str, SystemListing], asked: list[str] | None = None):
    def listing(kind: str) -> SystemListing:
        if asked is not None:
            asked.append(kind)
        return table.get(kind, SystemListing.NOT_LISTED)

    return listing


class TestEdenStartsGames:
    def test_an_eden_appimage_starts_games(self):
        assert _source("eden_appimage").starts_games is True

    def test_emudeck_still_does_not(self):
        assert _source("emudeck").starts_games is False


class TestTheSourceAnsweringForNoSystem:
    def test_retrodeck_answers_with_eden_switched_on_beside_it(self):
        assert _kind(answering_source((_source("retrodeck"), _source("eden_appimage")))) == "retrodeck"

    def test_a_frontend_answers_whole_machine_questions_even_with_eden_ordered_first(self):
        sources = (_source("eden_appimage"), _source("emudeck"))
        assert _kind(answering_source(sources)) == "emudeck"

    def test_eden_alone_answers(self):
        sources = (_source("retrodeck", enabled=False), _source("eden_appimage"))
        assert _kind(answering_source(sources)) == "eden_appimage"


class TestTheSourceAnsweringForOneSystem:
    def test_eden_answers_switch_where_retrodeck_has_no_switch_emulator_installed(self):
        sources = (_source("retrodeck"), _source("eden_appimage"))
        listing = _listing({"retrodeck": SystemListing.NOT_LISTED, "eden_appimage": SystemListing.STARTS})
        assert _kind(answering_source_for(sources, listing)) == "eden_appimage"

    def test_the_first_in_the_order_that_starts_it_answers(self):
        sources = (_source("retrodeck"), _source("eden_appimage"))
        listing = _listing({"retrodeck": SystemListing.STARTS, "eden_appimage": SystemListing.STARTS})
        assert _kind(answering_source_for(sources, listing)) == "retrodeck"

    def test_one_that_starts_it_wins_over_an_earlier_one_whose_program_is_unconfirmed(self):
        sources = (_source("retrodeck"), _source("eden_appimage"))
        listing = _listing({"retrodeck": SystemListing.UNESTABLISHED, "eden_appimage": SystemListing.STARTS})
        assert _kind(answering_source_for(sources, listing)) == "eden_appimage"

    def test_an_unconfirmed_one_answers_where_none_starts_it(self):
        sources = (_source("retrodeck"), _source("eden_appimage"))
        listing = _listing({"eden_appimage": SystemListing.UNESTABLISHED})
        assert _kind(answering_source_for(sources, listing)) == "eden_appimage"

    def test_where_none_lists_it_the_source_answering_for_no_system_answers(self):
        sources = (_source("emudeck"), _source("retrodeck"), _source("eden_appimage"))
        assert _kind(answering_source_for(sources, _listing({}))) == "retrodeck"

    def test_a_switched_off_source_never_answers(self):
        sources = (_source("retrodeck"), _source("eden_appimage", enabled=False))
        listing = _listing({"eden_appimage": SystemListing.STARTS})
        assert _kind(answering_source_for(sources, listing)) == "retrodeck"

    def test_with_one_source_that_starts_games_no_catalogue_is_asked(self):
        asked: list[str] = []
        sources = (_source("retrodeck"), _source("emudeck"))
        assert _kind(answering_source_for(sources, _listing({}, asked))) == "retrodeck"
        assert asked == []

    def test_eden_alone_beside_emudeck_is_asked_and_answers_its_system(self):
        sources = (_source("emudeck"), _source("eden_appimage"))
        listing = _listing({"eden_appimage": SystemListing.STARTS})
        assert _kind(answering_source_for(sources, listing)) == "eden_appimage"

    def test_nothing_switched_on_answers_none(self):
        assert answering_source_for((_source("retrodeck", enabled=False),), _listing({})) is None


class TestTheSwitchedOffSourceForOneSystem:
    def test_a_switched_off_eden_refuses_switch_where_retrodeck_does_not_start_it(self):
        sources = (_source("retrodeck"), _source("eden_appimage", enabled=False))
        listing = _listing({"eden_appimage": SystemListing.STARTS})
        assert switched_off_starting_source(sources, listing) == "eden_appimage"

    def test_a_switched_off_eden_refuses_nothing_retrodeck_starts(self):
        sources = (_source("retrodeck"), _source("eden_appimage", enabled=False))
        listing = _listing({"retrodeck": SystemListing.STARTS, "eden_appimage": SystemListing.STARTS})
        assert switched_off_starting_source(sources, listing) is None

    def test_a_switched_off_retrodeck_refuses_its_system_beside_eden(self):
        sources = (_source("retrodeck", enabled=False), _source("eden_appimage"))
        listing = _listing({"retrodeck": SystemListing.STARTS})
        assert switched_off_starting_source(sources, listing) == "retrodeck"

    def test_where_no_switched_off_source_lists_it_the_rule_for_no_system_stands(self):
        sources = (_source("retrodeck", enabled=False), _source("emudeck"))
        assert switched_off_starting_source(sources, _listing({})) == "retrodeck"


class TestStoredAppImage:
    @pytest.mark.parametrize(("value", "absolute"), [("/a/Eden.AppImage", True), ("a/Eden.AppImage", False)])
    def test_only_an_absolute_path_names_one(self, value, absolute):
        assert is_absolute_path(value) is absolute
