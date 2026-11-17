---
status: accepted
decided: 2026-11-17
---

# Extra content lands in the game's folder, is recorded on the install, and is offered per the resolver's statement

## Context

RomM keeps a Switch game's updates and DLC beside the base game, filed under the `update` and `dlc` categories, and a
download has so far left every such file on the server. Eden, the Switch emulator Tender starts as a standalone
AppImage, loads updates and DLC from packages lying in folders it scans, with no step that installs them; other
emulators want them installed into their own storage, or have no reading of this the resolver states. The vendored
resolver now answers the question (`extra_content_folders`): whether the entry a game starts with loads updates and
add-ons from folders, which folders it scans and how, which extensions it reads there, and whether the game's own folder
is one of them.

Three questions had to be settled: where the files go, how Tender knows they are there, and for which games it offers
them at all.

## Decision

1. **Extra content lands in the game's own folder, at the place RomM keeps it there** (`update/…`, `dlc/…`, or beside
   the base game), each file's place joined under the install's `rom_dir` through `safe_join`. A game RomM holds as one
   file owns no folder, and so has no extra content. Each file is fetched on its own, naming its one id, so it arrives
   as itself and needs no unpacking; something already lying at a file's place is never written over.
2. **The install record remembers the extra content downloaded** — `RomInstall.extra_content`, a child table keyed by
   RomM's file id, written and dropped with the install row. An uninstall removes the game's folder whole, and the extra
   content with it. Whether a game is installed, and whether its file is missing, depends on the game alone.
3. **Extra content is offered only where the resolver states the emulator entry the game starts with loads it from
   folders.** Tender keeps no list of platforms or emulators for it; a `null` is "not established" and offers nothing.
   Today that is the Eden AppImage's `switch` entry.
4. **A download asks, and an installed game's page offers the rest.** A download of such a game asks which update and
   DLC files to bring, ticking the newest update and every DLC file; the base game always downloads, and Cancel cancels
   it. The game page's UPDATES & DLC tab downloads or removes files for an installed game without touching the game.
   Removing one asks first: it is deleted here, and RomM keeps it — the confirm leg of backup-or-confirm.

## Consequences

- An emulator that loads updates from folders finds them only in a folder it scans. Where the resolver says the game's
  folder is not one, the tab says so and names the ROM folder to add as a game folder scanned to its subfolders; Tender
  changes no emulator setting. Eden scans its game folders beside a `-g` boot rather than before it, which the resolver
  states (`extra-content-scanned-beside-launch`); on the reference Deck a deep-scanned game folder's DLC was applied on
  a start from Steam all the same, so the tab says nothing about it.
- An emulator that wants updates installed gets no offer until the resolver states how it loads them; installing into an
  emulator's storage is not this decision.
- The extra-content download reuses the download machinery — the claim, the semaphore, the reservation, the queue and
  its frames — with frames marked `extra_content_only`, so the game's own button leaves them alone.
- The removed-game cleanup needs nothing of its own: it measures, bundles and removes `rom_dir` whole, and the rows go
  with the game's cascade.
- Where the answer lists both a folder registered before the launch and one scanned only beside it, which of them holds
  the game's folder is not stated, and the tab says nothing; that needs the resolver to state it.
