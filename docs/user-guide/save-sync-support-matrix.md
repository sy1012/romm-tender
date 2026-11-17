# Save sync support by platform

Save sync works **per game**: when a game is installed, its save is uploaded to RomM and pulled back before launch, so
you can carry on across devices. Standard cartridge saves work automatically. A few consoles store saves differently —
this page shows what syncs for each system today, and what's planned.

## How reliable is this page?

**Tender no longer decides what a save is from a table like this one.** It asks your machine, per game and per the
emulator that will launch it, every time it syncs — so the answer follows your actual core choice and your actual core
options rather than a row written in advance. This page is now background reading: it explains why a platform behaves
the way it does, and Tender's own answer is what governs.

Two things still matter when you read a row:

- **A ❌ often means "not with the settings that ship", not "impossible".** Several cores can write per-game saves if
  you change a core option — the rows below say which. Turning that on is not yet something Tender does for you, but it
  does now **notice**: change the option and the next sync reads the new answer.
- **Rows are stated for each platform's _default_ core.** You can override the core per system and per game, and a
  different core can behave differently — which is exactly why Tender asks per game. A save written beside the game file
  (usually RetroArch's `savefiles_in_content_dir`) keeps save sync off, and that is reported separately.

Most of this table is derived from libretro's documentation and from reading core source, not from watching each core
write a save. Where the [emu-atlas](https://github.com/danielcopper/emu-atlas) audit has corrected an earlier
assumption, this page reflects the audit.

## When save sync does nothing, and why

Where Tender cannot carry a game's saves, it says so when you start a sync yourself: **Sync Save Files**, a slot switch,
copying a save to another slot and restoring an older version all answer with the reason. The sync before a game starts
and the one after it exits pass such a game over without a message, and **Sync All Saves Now** counts it among the games
whose saves cannot be synced. A downloaded game's **Saves** tab is marked with a warning beside its title and gives the
reason in place of its save slots, whether or not a slot was set up for it before; a game that is not downloaded says
whether its saves will sync once it is, or that this could not be established. There are five reasons, and they mean
different things:

- **The emulator keeps one save card that all games share.** Standalone PCSX2 is the common case. Syncing it per game
  would copy other games' progress onto this one's record, so Tender leaves it alone.
- **The save is written inside the game file itself.** There is no separate file to carry.
- **The emulator files saves under the game's own identity**, which Tender cannot read yet — in the file name, for
  Dreamcast. Dreamcast, Nintendo 3DS and Wii U are here.
- **Where the emulator saves depends on the folder the game is started from.** RetroArch does this when its save folder
  is set as a relative path. Tender cannot tell which folder that is, so it leaves such a game alone.
- **What the emulator writes could not be established** — either nobody has audited that core yet, or the folder is
  known and the names inside it are not.

None of these is an error, and none of them stops a game launching. If you change the emulator for a game, the answer is
read again for the new one.

## Categories

|    | Meaning                                                                                                                                                                                                                                                        |
| -- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ✅ | **Synced today.** Your saves for this system carry across devices automatically. A few systems answer differently for a disc image than for a raw dump — where that is so, the note says which file gets you the per-game save.                                |
| 🔜 | **Planned.** This save type isn't synced yet, but it fits the model and is on the way in a future release.                                                                                                                                                     |
| ❌ | **Not synced yet.** This system's default core writes a _shared_ card (one file for many games), keeps saves outside the per-game save folder, or hasn't been pinned down yet — so it doesn't fit per-game sync today. Handled differently in a later release. |
| ⚪ | **No save data.** This system's emulator has no in-game save to sync (you can still use save states locally).                                                                                                                                                  |

## What syncs today ✅

Standard per-game cartridge saves sync automatically. That covers the large majority of systems — Nintendo (NES, SNES,
Game Boy / Color / Advance, N64, DS), Sega (Master System, Game Gear, Genesis / Mega Drive), PC Engine / TurboGrafx,
WonderSwan, Atari Lynx, Virtual Boy, and more.

**Sega CD depends on your game file.** A raw `.bin` dump saves per game and syncs; a `.chd`, `.cue` or `.iso` disc image
puts the save on a shared BRAM card that all your Sega CD games write to, which cannot be carried per game. Amiga is the
same story with different answers: a `.chd` CD32 image saves per game, while an `.adf` floppy writes into the disk image
itself, a `.lha` names a `WHDSaves` folder whose contents the core does not list, and an `.hdf` hard-disk image cannot
be established at all.

3DO and Neo Geo keep their saves in a subfolder of the emulator's own — `saves/3do/opera/per_game` and
`saves/neogeo/fbneo` — and Tender now looks there, because it takes each game's save folder from the emulator rather
than working it out itself. That has not yet been observed on a device.

!!! warning "3DO saves were not backed up by earlier versions"

    3DO once showed as ✅ on the assumption that the Opera core writes a plain `<game>.srm` into the save folder. It
    does not: Opera writes its NVRAM to `opera/per_game/` with a version number in the filename, and earlier versions
    of Tender never looked there. **If you played 3DO games with an earlier version, those saves were never uploaded
    to RomM.** This version looks where Opera writes them, which has not yet been observed on a device — check that
    your 3DO saves reach RomM before relying on it.

**GameCube and Wii sync on Dolphin (Standalone).** Tender reads the game's ID from the disc image — ISO, GCM, NKit,
CISO, GCZ, WBFS, WIA or RVZ — and from it finds the game's own save: on Wii, the title's folder in Dolphin's NAND
(`Wii/title/00010000/<id>/`); on GameCube, this game's `.gci` files in the disc region's `Card A` folder, which needs
Dolphin's slot A set to **GCI Folder** (RetroDECK's default) — a single shared memory card (`.raw`) holds every game's
saves and is left alone. Either way the save is carried to RomM as one `<game>.zip`, laid out the way Argosy, RomM's
Android app, lays it out, so the two can share it. Restoring replaces only that game's folder or files: other games'
saves in the same folder are never touched, and the save it replaces is kept in `.romm-backup` first. This has not yet
been observed on a device.

**Switch syncs on a standalone Eden AppImage.** Tender finds the game's application ID in the file's name (a `[0100…]`
tag), else in the tickets an NSP or NSZ lists, else in the tags of the other files in its folder (an update's or DLC's
ID is taken back to its game), and the Eden user it runs as from Eden's own profile list. The save is that game's folder
under `user/save/0000000000000000/<user>/<application id>` in Eden's NAND (or the save folder set in Eden's settings),
carried to RomM as one `<game>.zip` laid out under the application ID, the way Argosy lays it out. Where the game's ID
or the Eden user cannot be told — no tag, no readable package, no profile list yet — nothing is synced for that game and
Tender says it could not be established. Start Eden once and set it up yourself first: Tender does not install Eden's
keys or firmware, and does not download a game's updates or DLC. This has not yet been observed on a device.

**PSP syncs on PPSSPP (Standalone), for an `.iso`.** Tender reads the game's ID from the disc (`ULUS10064`, say) and
carries the game's save folders in PPSSPP's `PSP/SAVEDATA` — the ones named starting with that ID — to RomM as one
`<game>.zip`, each folder at the top the way Argosy lays it out. A folder of data the game installed from its disc is
not a save and is left alone, and so is every other game's folder: restoring replaces only the folders that were this
game's save, and refuses rather than write over anything else. A compressed image (`.cso`, `.chd`) or an EBOOT (`.pbp`)
is not read, so nothing is synced for it. A PlayStation Network release may save under the ID of its disc release;
Tender syncs the folders under the game's own ID. This has not yet been observed on a device.

The systems whose default core has been **watched writing a save on a stock RetroDECK install** are Game Boy / Color /
Advance, N64, Saturn, Neo Geo Pocket (Color) and Pokémon Mini. The rest of the ✅ rows follow the same standard `.srm`
convention and are expected to behave identically, but haven't been observed one by one.

## Coming soon 🔜

Per-game saves for these systems fit the sync model and are planned for a future release:

| System      | Notes                                                                                        |
| ----------- | -------------------------------------------------------------------------------------------- |
| PlayStation | Memory-card saves. The cores write them per game, but under a name Tender doesn't probe yet. |

A few less-common systems (some DOS, PICO-8, ST-V) may also gain support pending confirmation.

## Not synced yet ❌

These systems' default cores write a **shared card** — a single file holding the saves for _all_ your games — keep saves
outside the per-game save folder, or haven't been pinned down yet. A shared card can't be split per game without risking
other games' saves, so it doesn't fit per-game sync today. We're looking at safe ways to handle these in a future
release.

| System        | Why it doesn't sync today                                                                                                                                                                                                                         |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dreamcast     | Flycast ships with **Per-Game VMUs off**, so every game shares `vmu_save_A1.bin` and its siblings in RetroDECK's system folder. The core _can_ write per-game VMUs; the names it uses then aren't pinned down yet.                                |
| PlayStation 2 | The LRPS2 core ships with **shared memory cards on** (`Mcd001.ps2` / `Mcd002.ps2`). With that option off it writes one `<game>.ps2` card per game — which would fit per-game sync. The PCEE2 core always writes shared cards, in the same folder. |
| Neo Geo CD    | Ships writing one shared save. The core has a per-content mode; which one wins when loading isn't confirmed.                                                                                                                                      |
| Nintendo 3DS  | The Azahar core appears to use its own save subtree. Not confirmed on-device yet.                                                                                                                                                                 |
| Arcade (MAME) | NVRAM is stored separately by the emulator, not as a file named after your ROM.                                                                                                                                                                   |
| Amiga         | PUAE keeps an `.adf` floppy's save inside the disk image itself, so there is no separate file to carry. A `.lha` names a `WHDSaves` folder whose contents the core does not list, and an `.hdf` is not answered at all.                           |

## No save data ⚪

Many computer, arcade, and homebrew systems have no in-game battery save at all — there's simply nothing to sync (save
states still work locally). See the full table for specifics.

## Full platform list

??? note "Every platform (150)"

    Status of each platform's default emulator core. Some platforms offer alternative cores that may behave differently.

    | Platform | Status | Notes |
    | --- | --- | --- |
    | `amiga` | ❌ | An `.adf` floppy keeps the save inside the disk image; a `.lha` names a folder whose contents the core does not list; an `.hdf` is not answered |
    | `amstradcpc` | ❌ | Not synced |
    | `apple2` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `apple2gs` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `arcade` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `arcadia` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `astrocde` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `atomiswave` | ❌ | Shared VMU card (Flycast default; the core has a per-game mode) |
    | `consolearcade` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `cps` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `cps1` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `cps2` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `cps3` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `crvision` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `daphne` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `doom` | ❌ | Not synced |
    | `dreamcast` | ❌ | Shared VMU card (Flycast default; the core has a per-game mode) |
    | `easyrpg` | ❌ | Not synced |
    | `fmtowns` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `gamate` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `gameandwatch` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `gamecom` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `gc` | ✅ | Dolphin (Standalone) with slot A set to GCI Folder: the game's `.gci` files, as one zip — not yet observed on a device |
    | `gmaster` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `gx4000` | ❌ | Not synced |
    | `laserdisc` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `lcdgames` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `mame` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `mess` | ❌ | Not synced |
    | `model2` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `n3ds` | ❌ | Azahar core's own save subtree — not confirmed on-device |
    | `naomi` | ❌ | Shared VMU card (Flycast default; the core has a per-game mode) |
    | `naomi2` | ❌ | Shared VMU card (Flycast default; the core has a per-game mode) |
    | `naomigd` | ❌ | Shared VMU card (Flycast default; the core has a per-game mode) |
    | `neogeocd` | ❌ | Shared save (the core has a per-content mode) |
    | `neogeocdjp` | ❌ | Shared save (the core has a per-content mode) |
    | `ps2` | ❌ | Shared memory card by default (LRPS2), always (PCEE2); per-game `<game>.ps2` available as an LRPS2 core option |
    | `psp` | ✅ | PPSSPP (Standalone): the game's save folders (named by its ID) as one zip — `.iso` only; not yet observed on a device |
    | `pv1000` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `scummvm` | ❌ | Not synced |
    | `scv` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `supracan` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `switch` | ✅ | Eden (AppImage): the game's save folder for the Eden user, as one zip — not yet observed on a device |
    | `vsmile` | ❌ | Saves are stored separately by the emulator (MAME) |
    | `wii` | ✅ | Dolphin (Standalone): the game's title folder in the NAND, as one zip — not yet observed on a device |
    | `x68000` | ❌ | Not synced |
    | `amiga1200` | 🔜 | Planned |
    | `amiga600` | 🔜 | Planned |
    | `atarijaguar` | 🔜 | Planned |
    | `cdimono1` | 🔜 | Under review |
    | `cdtv` | 🔜 | Planned |
    | `dos` | 🔜 | Planned |
    | `pc` | 🔜 | Planned |
    | `pico8` | 🔜 | Planned |
    | `psx` | 🔜 | Planned |
    | `quake` | 🔜 | Planned |
    | `saturnjp` | 🔜 | Planned |
    | `stv` | 🔜 | Planned |
    | `wasm4` | 🔜 | Under review |
    | `windows3x` | 🔜 | Planned |
    | `windows9x` | 🔜 | Planned |
    | `3do` | ✅ | Per-game NVRAM in the Opera core's own `opera/per_game/` subfolder — not yet observed on a device |
    | `amigacd32` | ✅ | A `.chd` disc image saves per game; a raw `.bin` is not answered |
    | `atari2600` | ✅ | Synced |
    | `c64` | ✅ | Synced |
    | `famicom` | ✅ | Synced |
    | `fbneo` | ✅ | Synced |
    | `fds` | ✅ | Synced |
    | `gamegear` | ✅ | Synced |
    | `gb` | ✅ | Synced |
    | `gba` | ✅ | Synced |
    | `gbc` | ✅ | Synced |
    | `genesis` | ✅ | Synced |
    | `mark3` | ✅ | Synced |
    | `mastersystem` | ✅ | Synced |
    | `megacd` | ✅ | A raw `.bin` dump saves per game; a disc image uses a shared BRAM card |
    | `megacdjp` | ✅ | A raw `.bin` dump saves per game; a disc image uses a shared BRAM card |
    | `megadrive` | ✅ | Synced |
    | `megadrivejp` | ✅ | Synced |
    | `megaduck` | ✅ | Synced |
    | `multivision` | ✅ | Synced |
    | `n64` | ✅ | Synced |
    | `n64dd` | ✅ | Synced |
    | `nds` | ✅ | Synced |
    | `neogeo` | ✅ | Per-game saves in the FinalBurn Neo core's own `fbneo/` subfolder — not yet observed on a device |
    | `nes` | ✅ | Synced |
    | `ngp` | ✅ | Synced |
    | `ngpc` | ✅ | Synced |
    | `pc88` | ✅ | Synced |
    | `pcengine` | ✅ | Synced |
    | `pcenginecd` | ✅ | Synced |
    | `pcfx` | ✅ | Synced |
    | `plus4` | ✅ | Synced |
    | `pokemini` | ✅ | Synced |
    | `satellaview` | ✅ | Synced |
    | `saturn` | ✅ | Synced |
    | `sega32x` | ✅ | Synced |
    | `sega32xjp` | ✅ | Synced |
    | `sega32xna` | ✅ | Synced |
    | `segacd` | ✅ | A raw `.bin` dump saves per game; a disc image uses a shared BRAM card |
    | `sfc` | ✅ | Synced |
    | `sg-1000` | ✅ | Synced |
    | `sgb` | ✅ | Synced |
    | `snes` | ✅ | Synced |
    | `snesna` | ✅ | Synced |
    | `sufami` | ✅ | Synced |
    | `supergrafx` | ✅ | Synced |
    | `supervision` | ✅ | Synced |
    | `tg-cd` | ✅ | Synced |
    | `tg16` | ✅ | Synced |
    | `tic80` | ✅ | Synced |
    | `vic20` | ✅ | Synced |
    | `virtualboy` | ✅ | Synced |
    | `wonderswan` | ✅ | Synced |
    | `wonderswancolor` | ✅ | Synced |
    | `arduboy` | ⚪ | No save data |
    | `atari5200` | ⚪ | No save data |
    | `atari7800` | ⚪ | No save data |
    | `atari800` | ⚪ | No save data |
    | `atarilynx` | ⚪ | No save data |
    | `atarist` | ⚪ | No save data |
    | `atarixe` | ⚪ | No save data |
    | `bbcmicro` | ⚪ | No save data |
    | `chailove` | ⚪ | No save data |
    | `channelf` | ⚪ | No save data |
    | `colecovision` | ⚪ | No save data |
    | `fba` | ⚪ | No save data |
    | `intellivision` | ⚪ | No save data |
    | `j2me` | ⚪ | No save data |
    | `lowresnx` | ⚪ | No save data |
    | `lutro` | ⚪ | No save data |
    | `moto` | ⚪ | No save data |
    | `msx` | ⚪ | No save data |
    | `msx1` | ⚪ | No save data |
    | `msx2` | ⚪ | No save data |
    | `msxturbor` | ⚪ | No save data |
    | `odyssey2` | ⚪ | No save data |
    | `palm` | ⚪ | No save data |
    | `pc98` | ⚪ | No save data |
    | `ports` | ⚪ | No save data |
    | `spectravideo` | ⚪ | No save data |
    | `to8` | ⚪ | No save data |
    | `uzebox` | ⚪ | No save data |
    | `vectrex` | ⚪ | No save data |
    | `videopac` | ⚪ | No save data |
    | `vircon32` | ⚪ | No save data |
    | `x1` | ⚪ | No save data |
    | `zmachine` | ⚪ | No save data |
    | `zx81` | ⚪ | No save data |
    | `zxspectrum` | ⚪ | No save data |

---

_Coverage is reviewed against the emulator cores RetroDECK ships. Most rows still await on-device confirmation; see
[How reliable is this page?](#how-reliable-is-this-page) above. Last reviewed 2026-08-02, against the
[emu-atlas](https://github.com/danielcopper/emu-atlas) core audit as of 2026-07-24._
