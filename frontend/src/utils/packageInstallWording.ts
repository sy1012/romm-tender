/**
 * What the panel says about a game installed into its emulator from a package:
 * why a downloaded package was not installed — the download is kept then, so each
 * sentence says so — and the question an uninstall of the installed game asks.
 */

import type { PackageNotInstalled } from "../types";

/** The toast after a download whose package was not installed into its emulator. */
export function packageNotInstalledToast(romName: string, outcome: PackageNotInstalled): string {
  const game = romName || "the game";
  const installer = outcome.installer ?? "The emulator";
  const kept = "The downloaded package is kept.";
  switch (outcome.reason) {
    case "no_boot_file":
      return `${installer} could not install the package of ${game} — the licence may be missing. ${kept}`;
    case "did_not_finish":
      return `${installer} did not finish installing ${game}. ${kept}`;
    case "not_started":
      return `${installer} could not be started to install ${game}. ${kept}`;
    case "several_games":
      return `The packages of ${game} install more than one game, and Tender installs one game per download. ${kept}`;
    case "command_incomplete":
      return `Tender could not tell how ${installer} installs the package of ${game}. ${kept}`;
  }
}

export const PACKAGE_UNINSTALL_TITLE = "Uninstall the installed game?";

/** The uninstall's question for a game installed into its emulator from a package. */
export function packageUninstallDescription(romName: string): string {
  return `${romName || "This game"} is removed from the emulator's drive. Its saves stay, and it can be downloaded and installed again from RomM.`;
}
