"""Tests for ``domain.extra_content``: which files are a game's extra content, and which a download ticks."""

from __future__ import annotations

from typing import Any

import pytest

from domain.extra_content import (
    ExtraContentFile,
    UnknownExtraContent,
    chosen_extra_content,
    extra_content_files,
    newest_update,
    read_from_folders,
    ticked_by_default,
)


def _file(file_id: int, rel_path: str, category: str | None, size: int = 10, **extra: Any) -> dict[str, Any]:
    folder, _, name = rel_path.rpartition("/")
    return {
        "id": file_id,
        "file_name": name,
        "file_path": f"switch/Game/{folder}".rstrip("/"),
        "file_size_bytes": size,
        "category": category,
        **extra,
    }


def _game(*files: dict[str, Any], **flags: Any) -> dict[str, Any]:
    return {"id": 1, "full_path": "switch/Game", "has_multiple_files": True, "files": list(files), **flags}


def _extra(file_id: int, name: str, category: str = "update", modified: str | None = None) -> ExtraContentFile:
    """One file as ``extra_content_files`` reads it from RomM's payload."""
    detail = _game(_file(file_id, f"{category}/{name}", category, last_modified=modified))
    (found,) = extra_content_files(detail)
    return found


class TestWhichFilesAreExtraContent:
    def test_updates_and_dlc_are_listed_in_romm_s_order_with_their_place(self):
        detail = _game(
            _file(1, "Game.nsp", "game"),
            _file(2, "update/Game [v65536].nsp", "update", 300),
            _file(3, "dlc/Game DLC.nsp", "dlc", 40),
            _file(4, "manual/Game.pdf", "manual"),
        )

        files = extra_content_files(detail)

        assert [(f.file_id, f.rel_path, f.category, f.size_bytes, f.version) for f in files] == [
            (2, "update/Game [v65536].nsp", "update", 300, 65536),
            (3, "dlc/Game DLC.nsp", "dlc", 40, None),
        ]

    def test_an_update_lying_beside_the_base_game_keeps_its_place_there(self):
        detail = _game(_file(1, "Game.nsp", "game"), _file(2, "Game [UPD].nsp", "update"))

        assert [f.rel_path for f in extra_content_files(detail)] == ["Game [UPD].nsp"]

    def test_a_game_romm_holds_as_one_file_has_none(self):
        detail = {
            "id": 1,
            "full_path": "switch",
            "has_simple_single_file": True,
            "files": [_file(2, "Game [v1].nsp", "update")],
        }

        assert extra_content_files(detail) == ()

    def test_a_file_with_no_id_or_no_place_is_left_out(self):
        no_id = _file(2, "update/A.nsp", "update")
        no_id["id"] = None
        no_place = _file(3, "update/B.nsp", "update")
        no_place["file_path"] = "elsewhere/entirely"

        assert extra_content_files(_game(_file(1, "Game.nsp", "game"), no_id, no_place)) == ()

    def test_romm_s_modification_time_is_kept_and_its_update_time_stands_in(self):
        detail = _game(
            _file(1, "Game.nsp", "game"),
            _file(2, "update/A.nsp", "update", last_modified="2025-01-01T00:00:00Z"),
            _file(3, "update/B.nsp", "update", updated_at="2025-02-01T00:00:00Z"),
            _file(4, "update/C.nsp", "update"),
        )

        assert [f.modified for f in extra_content_files(detail)] == [
            "2025-01-01T00:00:00Z",
            "2025-02-01T00:00:00Z",
            None,
        ]


class TestTheNewestUpdate:
    def test_the_highest_version_tag_wins(self):
        files = [_extra(1, "Game [v131072].nsp"), _extra(2, "Game [v458752].nsp"), _extra(3, "Game [v65536].nsp")]

        newest = newest_update(files)

        assert newest is not None
        assert newest.file_id == 2

    def test_a_tag_wins_over_a_later_modification_time(self):
        files = [
            _extra(1, "Game [v65536].nsp", modified="2025-01-01T00:00:00Z"),
            _extra(2, "Game update.nsp", modified="2026-01-01T00:00:00Z"),
        ]

        newest = newest_update(files)

        assert newest is not None
        assert newest.file_id == 1

    def test_without_tags_the_latest_modification_time_wins(self):
        files = [
            _extra(1, "Old.nsp", modified="2025-03-01T00:00:00Z"),
            _extra(2, "New.nsp", modified="2025-06-01T00:00:00+00:00"),
            _extra(3, "Unknown.nsp"),
        ]

        newest = newest_update(files)

        assert newest is not None
        assert newest.file_id == 2

    def test_a_single_update_is_the_newest_whatever_it_states(self):
        newest = newest_update([_extra(1, "Update.nsp")])

        assert newest is not None
        assert newest.file_id == 1

    def test_of_several_that_state_nothing_none_is_the_newest(self):
        assert newest_update([_extra(1, "A.nsp"), _extra(2, "B.nsp")]) is None

    def test_dlc_is_never_an_update(self):
        assert newest_update([_extra(1, "DLC [v9].nsp", category="dlc")]) is None

    def test_the_tag_is_read_whatever_its_case(self):
        newest = newest_update([_extra(1, "Game [V2].nsp"), _extra(2, "Game [v1].nsp")])

        assert newest is not None
        assert newest.file_id == 1


class TestTickedByDefault:
    def test_the_newest_update_and_every_dlc_file(self):
        files = (
            _extra(1, "Game [v65536].nsp"),
            _extra(2, "Game [v131072].nsp"),
            _extra(3, "DLC one.nsp", category="dlc"),
            _extra(4, "DLC two.nsp", category="dlc"),
        )

        assert ticked_by_default(files) == frozenset({2, 3, 4})

    def test_updates_that_cannot_be_told_apart_are_all_left_unticked(self):
        files = (_extra(1, "A.nsp"), _extra(2, "B.nsp"), _extra(3, "DLC.nsp", category="dlc"))

        assert ticked_by_default(files) == frozenset({3})

    def test_no_extra_content_ticks_nothing(self):
        assert ticked_by_default(()) == frozenset()


class TestChosenExtraContent:
    def test_the_named_files_in_romm_s_order(self):
        detail = _game(_file(1, "Game.nsp", "game"), _file(2, "update/U.nsp", "update"), _file(3, "dlc/D.nsp", "dlc"))

        assert [f.file_id for f in chosen_extra_content(detail, [3, 2])] == [2, 3]

    def test_an_id_that_is_the_game_itself_is_refused(self):
        detail = _game(_file(1, "Game.nsp", "game"), _file(2, "update/U.nsp", "update"))

        with pytest.raises(UnknownExtraContent) as refused:
            chosen_extra_content(detail, [1, 2, 9])

        assert refused.value.reason == "unknown_extra_content"
        assert refused.value.details == {"file_ids": [1, 9]}

    def test_no_ids_choose_nothing(self):
        assert chosen_extra_content(_game(_file(1, "Game.nsp", "game")), []) == ()


class TestReadFromFolders:
    def test_an_extension_the_emulator_reads_is_read(self):
        assert read_from_folders(_extra(1, "Game.NSP"), (".nsp", ".xci")) is True

    def test_a_compressed_package_is_not(self):
        assert read_from_folders(_extra(1, "Game.nsz"), (".nsp", ".xci")) is False
        assert read_from_folders(_extra(2, "Game.xcz"), (".nsp", ".xci")) is False

    def test_without_extensions_it_is_not_established(self):
        assert read_from_folders(_extra(1, "Game.nsp"), ()) is None
