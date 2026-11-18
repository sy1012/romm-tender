---
status: accepted
decided: 2026-11-18
---

# A PS3 package is installed into RPCS3 and its download deleted; the install record points at the installed title

## Context

A PSN game reaches RomM as a package (`.pkg`), usually beside a licence package or a `.rap`/`.edat` file in the same
RomM game. RPCS3 cannot boot a package: it has to be installed into RPCS3's own drive first, after which the game lives
at `<dev_hdd0>/game/<title id>/` and boots from `USRDIR/EBOOT.BIN`. Until now a downloaded package stayed in the ROM
folder as the game's launch file, and the resolver refused to start it (`needs-installation`), so such a game could
never be started from Steam.

The vendored resolver now states the install (`package_install_command`): the RPCS3 entry's own command with
`--headless --installpkg <path>`, every package it takes and where each goes, and the boot file a game's folder holds
once the game is installed. RPCS3 installs every package and licence in a folder in one run, and exits `0` whatever came
of it, so the boot file standing afterwards is the one sign the game installed.

## Decision

1. **After a download is recorded, Tender asks the resolver how its content installs**, with the folder that holds the
   download's packages and licences (the download's own folder where they lie in more than one, or its one file), since
   RPCS3 reads only the folder it is handed, and installs it where the answer names a game. A download the answer names
   no game for is left as it is. The install runs to its end, bounded, as a child process the download's task can
   cancel; its extra content arrives first, so the same run installs it.
2. **Success is every boot file the answer names standing afterwards**, never the exit status.
3. **On success the downloaded files are deleted** — the download's whole folder, inside its system's ROM folder only.
   The game lives in RPCS3's drive, where the download would only duplicate it. **On failure they are kept**, recorded
   as before, and the completion says why.
4. **The install record points at the installed title**: `rom_dir` its folder in the drive, `file_path` its boot file as
   the host spells it (for Tender's own checks and the save answer), and a new column, `package_boot_file`, the boot
   file as the emulator spells it, which a start asks with. That column being set is what says the install was made so;
   nothing is inferred from a path.
5. **The launch verdict of such a game is not held to the system's accept-list**: an entry refused by the list alone
   starts it as far as Tender asks, and the launch command decides.
6. **Uninstall removes the title's folder, under the panel's confirmation, bounded by the drive's `game` folder** it
   lies in — never the drive's user folders, where the saves lie. Removed-game cleanup measures, captures and removes it
   under the same bound. The title is re-installable from RomM, so it takes the confirm leg.

## Consequences

- A PSN game downloaded through Tender starts from Steam, and its saves sync as any PS3 game's do, from the `PARAM.SFO`
  beside the installed boot file.
- The download is gone once installed: reinstalling means downloading again. A failed install leaves the package where
  it was, recorded as the game's install, refused at start as before.
- A set of packages that installs more than one game is refused, because one install record names one title.
- Updates and DLC of an installed title are not offered separately: they are installed with the game when ticked on its
  download, and the title's folder is RPCS3's, not a folder Tender downloads into.
- An install cancelled midway may leave a partial title folder in RPCS3's drive that no record names.
