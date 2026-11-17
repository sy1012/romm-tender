"""Detection — what emulator installations are present on a machine.

``detect(home, machine)`` probes the config markers of each known arrangement
and returns a handle for every one it finds — RetroDECK's Flatpak deploy too,
because a RetroDECK that has not been started, or left its first-run setup at
the storage step, has no marker and is an installation all the same
(``not-set-up``). Detection labels markers, it does
not partition: EmuDeck *is* a configured ``org.libretro.RetroArch``, so the
EmuDeck marker is checked before concluding "a bare RetroArch", and the EmuDeck
handle claims that Flatpak (its ``kinds`` carries both descriptions —
no second handle for the same RetroArch). Multiple arrangements coexist
ordinarily, so the result is a list, highest-priority first: RetroDECK, EmuDeck,
the bare RetroArch Flatpak, a bare native RetroArch, a standalone Eden AppImage. Ambiguity is a truthful
result — the caller chooses, atlas never silently picks a winner.

Every probe goes through the machine seam, so detection is fully provable from a
fixture machine.
"""

from __future__ import annotations

import os

from .installations import (
    EMUDECK_SETTINGS_SUFFIX,
    NATIVE_CFG_SUFFIX,
    RETRODECK_JSON_SUFFIX,
    STANDALONE_FLATPAK_CFG_SUFFIX,
    EdenAppImage,
    EmuDeck,
    Installation,
    BareRetroArchNative,
    RetroDeck,
    BareRetroArchFlatpak,
    eden_appimage_candidates,
    retrodeck_deployed,
)
from .machine import KIND_MISSING, Machine, RealMachine


def detect(home: str, machine: Machine | None = None, *, eden_appimage: str | None = None) -> list[Installation]:
    """Detect the emulator installations under *home*.

    *machine* defaults to the real machine; tests and conformance vectors pass a
    fixture. Returns the detected installations in probe order (an empty list
    when nothing is installed).

    *eden_appimage* names the Eden AppImage a standalone launch runs, as an
    absolute path (a relative one raises ``ValueError``). Named, it is the
    installation whether or not it is there — a named file that is missing is
    a handle whose health says so. Unnamed, the folders
    :data:`~atlas.installations.EDEN_APPIMAGE_FOLDERS` lists are searched, and
    any find yields the handle; several finds are stated by its health
    (``appimage-ambiguous``) rather than one picked. One keyword per
    standalone program, so a later one joins beside it without a vocabulary
    of program names in the signature.
    """
    if machine is None:
        machine = RealMachine()

    found: list[Installation] = []

    # A marker that exists but cannot be read or parsed is a PRESENT, broken
    # installation — detection triggers on existence; health states the rest
    # (REVIEW H10). The handles are live: they re-read their sources per query.
    if machine.path_kind(os.path.join(home, RETRODECK_JSON_SUFFIX)) != KIND_MISSING:
        found.append(RetroDeck(home, machine))
    # A deployed RetroDECK without its marker has not been started, or left
    # its first-run setup at the storage step, which deletes the marker it
    # wrote — an installation all the same: its health says not-set-up, and it
    # answers nothing else.
    elif retrodeck_deployed(machine, home):
        found.append(RetroDeck(home, machine, detected_by_deploy=True))

    emudeck_present = machine.path_kind(os.path.join(home, EMUDECK_SETTINGS_SUFFIX)) != KIND_MISSING
    if emudeck_present:
        found.append(EmuDeck(home, machine))

    # EmuDeck claims the bare Flatpak — same RetroArch, two descriptions,
    # one handle. Only an unclaimed Flatpak appears as its own installation.
    if not emudeck_present and machine.path_kind(os.path.join(home, STANDALONE_FLATPAK_CFG_SUFFIX)) != KIND_MISSING:
        found.append(BareRetroArchFlatpak(home, machine))

    if machine.path_kind(os.path.join(home, NATIVE_CFG_SUFFIX)) != KIND_MISSING:
        found.append(BareRetroArchNative(home, machine))

    # A standalone Eden AppImage, last: no frontend arranges it. The handle
    # searches again on every question, as every handle re-reads its sources.
    if eden_appimage is not None or eden_appimage_candidates(machine, home):
        found.append(EdenAppImage(home, machine, appimage=eden_appimage))

    return found
