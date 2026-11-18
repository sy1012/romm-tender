---
status: accepted
decided: 2026-11-18
---

# A save unit can be several folders under named roots, and a restore replaces only the folders the zip carries

## Context

Azahar keeps a 3DS title's progress in two places of its own on the emulated SD card: the title's save folder,
`Nintendo 3DS/<ID0>/<ID1>/title/<high>/<low>/data`, and, for a title granted one, its extdata folder,
`Nintendo 3DS/<ID0>/<ID1>/extdata/<HIGH>/<LOW>`. The save folder is the title's alone, the extdata folder that of the
extdata id the title is granted, and either may be missing — a title that never saved, or one that keeps its progress in
one of them alone. The vendored resolver now answers such a save with a fourth unit kind, `own-folders-by-archive-root`:
each folder paired with the name it is zipped under, `data` and `extdata`, stated even where neither exists yet.

Argosy, RomM's Android client, zips the same save (`N3dsFolderHandler`) as the save folder's contents under `data/` and
the extdata folder's under `extdata/`, and restores it by replacing each folder whose root the zip carries, keeping the
other, and refusing a zip with any other top-level entry; a legacy zip of `data/` alone restores the save and keeps the
extdata. A zip meets Argosy's only when it is laid out alike, and a zip of `data/` alone has to restore without touching
extdata it knows nothing about.

## Decision

1. **A fourth shape of `SaveUnit`**: `archive_roots`, `(root name, folder)` pairs, the names distinct single path
   components and the folders absolute. Only the resolver's `own-folders-by-archive-root` statement makes one. The zip
   holds each folder that exists under its root name, Argosy's layout; no folder existing means no zip.
2. **An unpack checks every entry before writing anything**: each must be a file inside a folder at the zip's top named
   as one of the unit's roots, the rest a path `safe_join` keeps under that root's folder. A file at the zip's top, a
   folder under any other name, or anything else refuses the whole zip.
3. **A restore replaces each folder whose root the zip carries files under, whole, and leaves every other folder as it
   is.** It never removes a folder the zip does not carry. The folders replaced are moved aside, the new ones moved in,
   and the aside ones deleted only once every one is in; a failure puts them all back.
4. **Clearing the unit removes each of its folders**, and refuses where one is a link or no folder.

## Consequences

- Tender and Argosy read each other's 3DS zips, a `data/`-only zip included, and that zip restores the title's save
  while the extdata on the machine stays.
- A restore is not an exact copy of the zip's moment: restoring a zip that holds no extdata, over a machine whose
  extdata is newer, leaves the two folders from different moments. The alternative — removing a folder the zip lacks —
  reads an absence as "empty", where a zip without `extdata/` usually comes from a client that never looked for it; the
  local zip in `.romm-backup` would still hold what was removed, but nothing would tell the player to look there.
- Two titles granted the same extdata id would each name that folder as theirs, and a restore of either replaces it for
  both, as it does in Argosy.
