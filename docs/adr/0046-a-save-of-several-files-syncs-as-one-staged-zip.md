---
status: accepted
decided: 2026-11-16
---

# A save of several files syncs as one staged zip

## Context

Save sync moves one regular file per save. Its identity is `(rom, slot, local file name)`, the decision the gavel core
makes reads only numbers and hashes — size, mtime, content size, content hash — and every other step (the probe, the
measure, upload, download, the `.romm-backup` backup, rollback, version history, the removed-game cleanup) opens or
stats that one file.

Two save shapes on the systems this fork is after are not one file:

- **A folder per game.** Dolphin keeps a Wii game's save in its emulated NAND as the folder
  `Wii/title/00010000/<title id>/data/`: a `banner.bin` and one or more files the game names itself. The resolver
  answers such a save with a group of granularity `per-game-directory` and no file list, and says to move the folder
  whole. RPCS3, Cemu and Azahar answer the same shape.
- **A game's files in a shared folder.** Dolphin's GameCube saves, with a slot set to a GCI folder (`SlotA = 8`, the
  setting on the reference Deck), are one `.gci` file per save inside `GC/<region>/Card A/`, every game's side by side.
  Which files are a game's is decided by the game code in each file's header (the resolver's `gci_members` rule).

RomM stores a zip as a save and answers its `content_hash` as an MD5 over the sorted `name:md5(entry)` lines of its
entries, which Tender already reproduces (`domain/save_hash.combine_zip_entry_hashes`).

## Decision

**A save of several files is a save unit, and it syncs as one zip Tender stages for it.**

1. **The unit.** The answer carries a `SaveUnit`: a root folder and which of its files are the save — every file below
   the root (a folder per game), or a named set of files directly in it (a game's files in a shared folder). What the
   root is and which files are members is the emulator's answer, as every save place already is; Tender holds no rule of
   its own for either.
2. **The staged zip.** The unit's stand-in is `<rom stem>.zip` in a staging folder of Tender's own, one per ROM, and
   that staging folder is the answer's sync directory. Every existing step — matching by name, the decision, upload,
   download, the backup, slots, rollback, version history — handles the zip as the one file it already handles. The
   upload sends it under its own name, so RomM files it as `<rom stem>.zip`.
3. **Packed before it is looked at.** Before anything measures the game's local saves, the zip is rebuilt from the unit:
   entries sorted, each named by its path below the root with `/` separators — under a top-level folder name where the
   answer gives one, which is how Argosy lays out a folder save and so how the zip meets saves other RomM clients upload
   — a fixed timestamp on every entry, and the zip's own mtime set to the newest member's — so the same files always
   give the same bytes, and the decision's mtime comparisons keep their meaning. A unit with no files has no zip, which
   reads as no local save, as a missing file does.
4. **Unpacked after it is written.** When a download or a rollback has written the zip, it is unpacked into the unit:
   every entry passes `safe_join` against the root, and the files are written to a temporary folder beside the root
   first. For a folder per game, the old folder is moved aside, the new one moved in, and the old one deleted only once
   that has succeeded. For a member set, the members the answer named are replaced by the entries and nothing else in
   the folder is touched.
5. **The backup is the zip's.** The download's `.romm-backup` step moves the previous zip aside before the new one
   lands, and that zip was packed from the unit a moment before, so the files the unpack replaces are always kept.
6. **Standalone emulators are tagged by their identity.** A save of an emulator that is not a libretro core is uploaded
   with the resolver's `emulator` identity, lowercased (`dolphin`, `pcsx2`, …), where it was `retroarch`. The tag is
   RomM's folder for the save and cannot be changed once a save carries it.

**A unit comes only from an answer that says the root is this game's own.** A `per-game-directory` group alone does not
say so: RPCS3 answers that granularity with the PARENT of every title's folder, and packing that as one game's save
would restore every other game's saves over theirs. So no answer the vendored resolver gives today becomes a unit; the
resolver's answer gains an explicit statement that a group's folder, or its named member set, is the game's own, and
only that statement makes one.

Not covered: following a moved save directory, the adoption rename and the removed-game cleanup leave a unit's own files
alone rather than guessing at them — the cleanup reaches the staged zip, never the unit.

## Consequences

- No step downstream of the probe learns that a save can be a folder; the cost is two hooks — the pack before the probe
  and the unpack after a write — and a missed hook is the risk: a path that reads the staged zip without packing first
  reads the unit as it was at the last pack.
- Disk space of about one zip per unit save, kept beside Tender's data; a rebuild each time a game's saves are looked
  at, which for save folders measured in kilobytes is milliseconds.
- The version history and rollback that a multi-file save had turned off (it counted several local names) apply to a
  unit, because it is one name. Rolling back restores every member together, which a set of separately synced files
  could not.
- A unit's save on RomM is a zip, so it is only useful to another client that unpacks it the same way; a single-file
  save stays as it was.
