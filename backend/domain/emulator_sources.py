"""Emulator sources — their order, their switches, and which one answers a game's questions.

An emulator source is what the resolver calls an installation, named by its
kind (GLOSSARY.md, "Emulator source"). This module decides from the detected
kinds and the user's stored preferences alone; detecting and storing are the
callers'. The stored preferences are keyed by kind, never by a folder, so a
source that moves keeps its place and its switch.

Pure compute — no I/O, no state mutation.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

from domain.refusal import DomainRefused

if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Iterable, Sequence

RETRODECK = "retrodeck"
EMUDECK = "emudeck"
EDEN_APPIMAGE = "eden_appimage"

# Where the order and the switched-off kinds are stored in ``settings.json``.
ORDER_SETTING = "emulator_source_order"
SWITCHED_OFF_SETTING = "emulator_sources_off"

# Where the Eden AppImage the user named is stored in ``settings.json``: an
# absolute path, or ``""`` for none, which leaves the resolver to search for one.
EDEN_APPIMAGE_SETTING = "eden_appimage"

# The kinds Tender starts games through.
_STARTING_KINDS = frozenset({RETRODECK, EDEN_APPIMAGE})

# The kinds whose catalogue the resolver states for one system only: such a
# source answers that system's games and never a question about the whole
# machine, wherever the user put it in the order.
_SINGLE_SYSTEM_KINDS = frozenset({EDEN_APPIMAGE})


class SystemListing(Enum):
    """How a source's catalogue lists one system, as far as choosing the source that answers it goes.

    ``STARTS``: an entry for the system whose program is there. ``UNESTABLISHED``:
    an entry, and whether its program is there is not established. ``NOT_LISTED``:
    no entry, every entry not installed, or a catalogue that could not be read.
    """

    STARTS = "starts"
    UNESTABLISHED = "unconfirmed"
    NOT_LISTED = "not_listed"


@dataclass(frozen=True, slots=True)
class ArrangedSource:
    """One detected source in the user's order.

    ``starts_games`` says whether Tender can start a game through this source
    today; it is a property of the kind, not of the switch.
    """

    kind: str
    enabled: bool
    starts_games: bool


class SourcesReading(Protocol):
    """One reading of the emulator sources, and the answers asked through it.

    Taken by the adapter that detects the sources — per question for a call from
    the panel, and once by a run that asks the same questions for many games and
    hands it down — and every answer asked through it is kept for as long as the
    reading is. A service reads which sources it found and their arrangement;
    the installations are the resolver's own handles, and only an adapter puts
    questions to them.
    """

    @property
    def installations(self) -> tuple[Any, ...]:
        """The resolver's handles detected for this reading, in its probe order."""
        ...

    @property
    def sources(self) -> tuple[ArrangedSource, ...]:
        """Every detected source, in the user's order."""
        ...

    @property
    def answering(self) -> ArrangedSource | None:
        """The source a question about no one system goes to, or ``None`` where none answers."""
        ...

    def answering_for(self, system: str) -> ArrangedSource | None:
        """The source a question about one of *system*'s games goes to (:func:`answering_source_for`)."""
        ...

    def switched_off_starting_for(self, system: str | None) -> str | None:
        """The kind of the switched-off source that would start a *system* game, or ``None``.

        :func:`switched_off_starting_source`, with *system*'s listing where one is named.
        """
        ...

    @property
    def detection_failed(self) -> bool:
        """Whether detecting the sources raised, so that none detected establishes nothing about any of them."""
        ...

    def no_answer_reason(self) -> str:
        """Why no source answers: :data:`NO_SOURCE_DETECTED` or :data:`ALL_SOURCES_SWITCHED_OFF`."""
        ...

    def answering_installation(self, system: str | None = None) -> Any:
        """The resolver's handle for :meth:`answering_for` *system*, or for :attr:`answering` without one.

        ``None`` where no source answers.
        """
        ...

    def installation(self, kind: str) -> Any:
        """The resolver's handle for the detected source of *kind*, or ``None``."""
        ...

    def remember[T](self, question: Hashable, ask: Callable[[], T]) -> T:
        """The answer to *question* through this reading, asked on its first use only."""
        ...


def arrange_sources(
    *, detected: Sequence[str], stored_order: Sequence[str], switched_off: Iterable[str]
) -> tuple[ArrangedSource, ...]:
    """The detected sources in the order the user sees them, each with its switch.

    *detected* is in the resolver's probe order, which is the default order.
    A stored order ranks the kinds it names; a detected kind it does not name
    follows them, in probe order, so a source seen for the first time joins at
    the end — except a single-system source, which joins at the front
    (:func:`_merged_order`). Switched-off is a deny-list, so a source seen for the first time is
    on. A stored kind that is not detected now keeps its place in the stored
    order but is not listed.
    """
    off = frozenset(switched_off)
    return tuple(
        ArrangedSource(kind=kind, enabled=kind not in off, starts_games=kind in _STARTING_KINDS)
        for kind in _merged_order(detected=detected, stored_order=stored_order)
        if kind in detected
    )


def answering_source(sources: Sequence[ArrangedSource]) -> ArrangedSource | None:
    """The source a question about no one system goes to, or ``None``.

    The first switched-on source in the order that starts games and answers
    for more than one system; otherwise the first switched-on source that
    answers for more than one, which answers for a start through that source's
    own frontend (``starts_games`` is false on it); otherwise the first
    switched-on source. ``None`` when nothing is detected or every detected
    source is switched off — :func:`no_answering_source_reason` tells the two
    apart.
    """
    enabled = [source for source in sources if source.enabled]
    whole_machine = [source for source in enabled if source.kind not in _SINGLE_SYSTEM_KINDS]
    starting = next((source for source in whole_machine if source.starts_games), None)
    if starting is not None:
        return starting
    if whole_machine:
        return whole_machine[0]
    return enabled[0] if enabled else None


def answering_source_for(
    sources: Sequence[ArrangedSource], listing: Callable[[str], SystemListing]
) -> ArrangedSource | None:
    """The source a question about one system's games goes to, or ``None``.

    *listing* answers a kind's :class:`SystemListing` for that system, and is
    asked only where more than one source could answer. The first switched-on
    source in the order that starts games and whose catalogue holds an entry
    for the system whose program is there (:attr:`SystemListing.STARTS`);
    otherwise the first such source holding one whose program is not
    established; otherwise :func:`answering_source`.
    """
    fallback = answering_source(sources)
    starting = [source for source in sources if source.enabled and source.starts_games]
    if not starting or starting == [fallback]:
        return fallback
    listed = [(source, listing(source.kind)) for source in starting]
    for wanted in (SystemListing.STARTS, SystemListing.UNESTABLISHED):
        found = next((source for source, said in listed if said is wanted), None)
        if found is not None:
            return found
    return fallback


def switched_off_starting_source(
    sources: Sequence[ArrangedSource], listing: Callable[[str], SystemListing] | None = None
) -> str | None:
    """The kind of the detected source that would start a game while it is switched off, or ``None``.

    A start is refused while this answers a kind. With the *listing* of the
    game's system, the source is the first switched-off one that starts games
    and lists the system (:attr:`SystemListing.STARTS` or ``UNESTABLISHED``),
    unless the source :func:`answering_source_for` names lists it too, which
    then takes the start over. Without one, or where no switched-off source
    lists it: ``None`` while a switched-on source starts games, and also where
    no source that starts games is detected at all — that start goes ahead and
    fails on its own, because a source that is not listed has no switch to
    turn back on; otherwise the first switched-off source that starts games.
    """
    if listing is not None:
        listed = (SystemListing.STARTS, SystemListing.UNESTABLISHED)
        answering = answering_source_for(sources, listing)
        if answering is not None and answering.starts_games and listing(answering.kind) in listed:
            return None
        off = next(
            (s.kind for s in sources if not s.enabled and s.starts_games and listing(s.kind) in listed),
            None,
        )
        if off is not None:
            return off
    if any(source.enabled and source.starts_games for source in sources):
        return None
    return next((source.kind for source in sources if source.starts_games), None)


# Why an emulator list could not be given: no source answers at all (the first
# two), or the answering source's catalogue was refused — sealed (EmuDeck's,
# which the resolver cannot read yet), a systems file ES-DE refuses to load, a
# RetroDECK that is installed but has not been set up yet, or any other reason
# nobody could read one.
NO_SOURCE_DETECTED = "no_source"
ALL_SOURCES_SWITCHED_OFF = "switched_off"
CATALOGUE_SEALED = "sealed"
CATALOGUE_INVALID = "catalogue_invalid"
CATALOGUE_NOT_SET_UP = "not_set_up"
CATALOGUE_UNAVAILABLE = "unavailable"

# What a source's catalogue is, as the settings row reports it: read, sealed,
# or unavailable — every other refusal, a broken systems file among them.
CATALOGUE_READ = "read"


def no_answering_source_reason(sources: Sequence[ArrangedSource]) -> str:
    """Why :func:`answering_source` found none: nothing detected, or everything switched off."""
    return ALL_SOURCES_SWITCHED_OFF if sources else NO_SOURCE_DETECTED


# Tender's own finding for a source that found several AppImages of its
# emulator and runs none of them until the user names one; ``data`` holds the
# ``candidates``, one path per line.
SEVERAL_APPIMAGES = "several-appimages"


@dataclass(frozen=True, slots=True)
class SourceFinding:
    """One health finding of a source: the resolver's stable code and the facts it established."""

    code: str
    data: dict[str, str]


@dataclass(frozen=True, slots=True)
class SourceReport:
    """What the settings list shows for one detected source.

    ``root`` is the folder the resolver gives as the source's root, for display
    only, and ``None`` where the resolver did not read it from the source's
    settings — for a source with no roots question, while a finding says its
    settings file was not read. ``findings`` are the resolver's, less a missing-root finding about
    a root Tender does not use, plus Tender's own ``roots-assumed``
    (:mod:`domain.source_roots`). ``catalogue`` is :data:`CATALOGUE_READ`,
    :data:`CATALOGUE_SEALED` or :data:`CATALOGUE_UNAVAILABLE`.
    """

    kind: str
    enabled: bool
    starts_games: bool
    root: str | None
    findings: tuple[SourceFinding, ...]
    catalogue: str


def move_source(*, kind: str, offset: int, detected: Sequence[str], stored_order: Sequence[str]) -> tuple[str, ...]:
    """The order to store after moving *kind* one place up (``-1``) or down (``+1``).

    A move swaps *kind* with its nearest DETECTED neighbour, because only
    detected sources are listed and a swap with a kind nobody sees would look
    like nothing happened. The answer is the whole merged order, undetected
    stored kinds included, so storing it keeps their places.

    Refuses ``unknown_source`` for a kind that is not detected, and
    ``cannot_move`` for a move past either end of the list.
    """
    if offset not in (-1, 1):
        raise ValueError(f"a source moves one place at a time, not {offset}")
    if kind not in detected:
        raise DomainRefused("unknown_source", f"No emulator source of kind {kind!r} is detected.", kind=kind)
    order = list(_merged_order(detected=detected, stored_order=stored_order))
    listed = [candidate for candidate in order if candidate in detected]
    position = listed.index(kind)
    neighbour_position = position + offset
    if not 0 <= neighbour_position < len(listed):
        raise DomainRefused("cannot_move", f"The emulator source {kind!r} cannot move further.", kind=kind)
    here, there = order.index(kind), order.index(listed[neighbour_position])
    order[here], order[there] = order[there], order[here]
    return tuple(order)


def switch_source(*, kind: str, enabled: bool, detected: Sequence[str], switched_off: Sequence[str]) -> tuple[str, ...]:
    """The switched-off kinds to store after switching *kind* on or off.

    Refuses ``unknown_source`` for a kind that is not detected: only a listed
    source has a switch. Kinds already in the list keep their order.
    """
    if kind not in detected:
        raise DomainRefused("unknown_source", f"No emulator source of kind {kind!r} is detected.", kind=kind)
    remaining = tuple(candidate for candidate in switched_off if candidate != kind)
    return remaining if enabled else (*remaining, kind)


def stored_kinds(value: object) -> tuple[str, ...]:
    """A stored list of kinds, or none where the stored value is not a list; non-text entries are dropped."""
    if not isinstance(value, list):
        return ()
    return tuple(kind for kind in value if isinstance(kind, str))


def is_absolute_path(value: str) -> bool:
    """Whether *value* is an absolute path on this host, which is what the resolver takes an AppImage's name as."""
    return posixpath.isabs(value)


def _merged_order(*, detected: Sequence[str], stored_order: Sequence[str]) -> tuple[str, ...]:
    """Every detected single-system kind the stored order does not name, then the stored order, then the rest.

    Both unnamed groups keep probe order. A single-system source goes first because a whole-machine
    frontend can list that system with an entry Tender cannot start (RetroDECK's ES-DE finds an Eden
    AppImage itself and answers it as "Eden (Standalone)", whose start through RetroDECK is not
    established), and whichever stands first for the system answers it.
    """
    stored = list(dict.fromkeys(stored_order))
    unnamed = [kind for kind in detected if kind not in stored]
    single = [kind for kind in unnamed if kind in _SINGLE_SYSTEM_KINDS]
    return (*single, *stored, *(kind for kind in unnamed if kind not in _SINGLE_SYSTEM_KINDS))
