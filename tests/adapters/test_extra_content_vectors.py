"""Tender's offer of extra content is the resolver's answer, on every recorded machine that asks it.

Each vector in ``tests/adapters/atlas_vectors/`` whose expectations hold an
``extra_content_folders`` answer is asked its own question live, and that
answer is read through Tender's reading module
(:func:`adapters.atlas_extra_content.read_extra_content`). Compared: offered
exactly where the recorded answer states the emulator loads from folders, and
then the game folder's verdict and the extensions as recorded.
"""

from __future__ import annotations

from typing import Any

import pytest
from _atlas_machines import fixture_machine, select, vectors_asking
from _vendor import atlas

from adapters.atlas_extra_content import read_extra_content

_VECTORS = vectors_asking("extra_content_folders")


def _asked(vector: dict[str, Any]) -> Any:
    inp = vector["input"]
    query = inp["extra_content_query"]
    installation = select(atlas.detect(inp["home"], fixture_machine(inp)), query.get("installation"))
    return installation.extra_content_folders(
        query["system"], label=query.get("label"), content_path=query.get("content_path")
    )


def test_the_copy_holds_machines_that_ask_it():
    assert _VECTORS


@pytest.mark.parametrize(("stem", "vector"), _VECTORS, ids=[v["name"] for _s, v in _VECTORS])
def test_the_offer_is_the_recorded_answer(stem: str, vector: dict[str, Any]) -> None:
    recorded = vector["expected"]["extra_content_folders"]

    view = read_extra_content(_asked(vector))

    assert view.offered is (recorded["loads_from_folders"] is True), stem
    if view.offered:
        assert view.game_folder_scanned == recorded["content_folder_scanned"]
        expected = tuple(dict.fromkeys(ext for folder in recorded["folders"] for ext in folder["extensions"]))
        assert view.extensions == expected
