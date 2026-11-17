---
status: accepted
decided: 2026-11-17
---

# The answering source is chosen per system

## Context

Every question about a game — its emulator list, its launch command, its save, its firmware — goes to one emulator
source, the answering source. Until now one source answered every game: RetroDECK while it was detected and switched on,
wherever it stood in the order, because every game started through it.

The vendored resolver now detects a standalone Eden AppImage (`eden_appimage`): Eden, the Switch emulator, run as the
one file the user downloaded, with no frontend around it. It answers for one system, `switch`, with one entry that is
startable through the AppImage itself, and it places a Switch game's save. Tender can start games through it. A user on
a Deck typically has RetroDECK for everything else, and RetroDECK's catalogue is ES-DE's, which declares `switch` with
emulator entries of its own whether or not any of them is installed.

So two sources now start games, and one of them answers for a single system. One answering source for every game cannot
express that: RetroDECK answering every game would never start a Switch game through Eden, and Eden answering every game
would answer nothing but Switch.

## Decision

**For a game of system _S_, the answering source is chosen for _S_.** It is the first switched-on source in the user's
order that starts games and whose catalogue holds an entry for _S_ whose program is there (`startable`); failing that,
the first such source holding an entry whose program is not established (`unestablished`); failing both, the source
answering for no system.

1. **"Lists _S_" is read off the entries' availability, not off the systems list.** A frontend's catalogue declares
   systems it has no installed emulator for: RetroDECK's `switch` would win wherever RetroDECK stands first and leave
   the user's Eden unused. An entry the resolver states `not-installed` therefore lists nothing, and neither does a
   catalogue that raised or was refused.
2. **The user's order still decides between sources that both start _S_.** A RetroDECK with an installed Switch
   emulator, ordered above the Eden AppImage, answers Switch; moved below it, Eden does. RetroDECK's ES-DE finds an Eden
   AppImage in `~/Applications` by itself and states its "Eden (Standalone)" entry `startable`, though Tender's start
   through RetroDECK refuses it (the environment its start needs is not stated) — seen on the reference Deck. So a
   source that answers for one system joins the order at the front the first time it is detected, rather than at the
   end; once the user moves any source, the whole order is stored and that place is theirs. Skipping a source whose
   start would be refused was the alternative: it needs a launch command, which needs a game's file, at a point where
   only the system is known.
3. **The source answering for no system** — for the firmware inventory, whether a set-up source answers for saves at
   all, what a content folder accepts, and as the fallback — is the first switched-on source that starts games and
   answers for more than one system, then the first that answers for more than one, then the first switched-on source. A
   source that answers for one system is never asked about the whole machine while another is switched on, wherever the
   user puts it in the order.
4. **Asked only where it can matter.** With one switched-on source that starts games and answering for no system,
   nothing beyond today's questions is asked. Otherwise each such source's catalogue is asked for _S_ once per reading.
5. **The launch check is asked for the game's system.** A switched-off source that starts games and lists _S_ refuses
   the start unless the source answering _S_ lists it too; without a system, or where no switched-off source lists it,
   the check is the one for no system it was.
6. **A platform's system** is asked of the source answering for no system, and where that source has no switched-on
   system for the platform, of each other switched-on source that starts games in the user's order.

## Consequences

- RetroDECK-only users see no change: one source starts games, so every rule above reduces to the one before.
- A RetroDECK and an Eden AppImage side by side ask RetroDECK's catalogue once per system per reading, a question the
  emulator list already asks; a library sync takes one reading per run.
- Which source answers a game can now change when a program is installed or removed in a source, not only when the user
  switches or moves one. A stored pick is a label of the source that answered when it was made; a label the new source
  does not offer falls back to that source's default, as a pick whose entry went away always has.
- What RetroDECK's own `switch` entries answer on a Deck without a Switch emulator installed in RetroDECK has not been
  observed; the rule does not depend on it, because only a `startable` or `unestablished` entry lists a system.
- A further single-system source (another standalone emulator) joins by naming its kind as one that starts games and
  answers for one system; nothing else in the rule changes.
