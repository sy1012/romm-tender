---
status: accepted
decided: 2026-11-17
---

# A save unit can be folders picked by a name prefix, and a restore replaces only the folders the answer named

## Context

PPSSPP keeps a PSP game's saves as folders directly in one `PSP/SAVEDATA` folder every game shares, each folder named
starting with the game's nine-character id (`ULUS10064DATA00`, `ULUS10064SETTINGS`). A game's installed data — a folder
the game itself copies from the disc to load faster — sits beside them under the same id (`ULUS10064INSTALL`), and is
not a save. The vendored resolver now answers such a save with a third unit kind, `own-folders-by-prefix`: the prefix,
and the folders starting with it that are the game's save, read off each folder's `PARAM.SFO`, installed data left out;
possibly none, for a game never saved.

Argosy, RomM's Android client, carries the same save as one zip holding each folder at its top
(`ULUS10064DATA00/PARAM.SFO`), and restores it by deleting **every** folder in `SAVEDATA` whose name starts with the id
and then unpacking. A zip meets Argosy's only when it is laid out alike, so the layout is not ours to choose. The
restore is a different matter: deleting every folder starting with the id deletes the installed data too, and that data
is in no zip — Tender packs the folders the answer names, not every folder under the prefix.

## Decision

1. **A third shape of `SaveUnit`**: a root, a `prefix`, and `members` naming the folders directly in the root that are
   the save — possibly none. Only the resolver's `own-folders-by-prefix` statement makes one. The zip holds each member
   folder at its top, laid out as Argosy lays it.
2. **An unpack checks every entry before writing anything**: each must be a file inside a folder at the zip's top whose
   name starts with the prefix (ASCII case-insensitively), the folder name a plain path component and the rest a path
   `safe_join` keeps under that folder. A file at the zip's top, or anything else, refuses the whole zip.
3. **A restore replaces the member folders and nothing else.** The member folders are moved aside, the zip's folders
   moved in, and the aside ones deleted only once every one is in; a failure puts them back. A folder the zip brings is
   created only where nothing lies at its name: where a folder that is not a member is there — installed data, or
   anything else the answer did not name — the unpack refuses with nothing written. Every folder a restore removes is
   therefore one the zip in `.romm-backup` holds.
4. **Clearing the unit removes its member folders only**, and refuses where a member is a link or no folder.

## Consequences

- A restore never loses installed data, and never a folder of another game. The cost is a refusal where Argosy would
  succeed: a zip carrying a folder named like one of the game's non-save folders fails the download loudly, the unit as
  it was.
- A save under a different id than the one the answer names is not this unit's. A PSN release may save under its disc
  release's id; the resolver says so (`psn-save-prefix-may-differ`), and Tender still syncs the folders under the id the
  answer names, and refuses a zip laid out under another.
- A game whose save folders have not been read cleanly has no unit: the answer is a hole, and nothing is synced.
