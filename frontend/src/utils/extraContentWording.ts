/**
 * The words a game's extra content — its update and DLC files on RomM — is
 * shown in: the UPDATES & DLC tab, the question a Download asks, the removal's
 * confirmation and the toasts. Where Eden's settings are named, the user guide's
 * "Switch updates and DLC" says the same.
 */

import type { DownloadCompleteEvent, ExtraContentFile } from "../types";
import { formatBytes } from "./formatters";

export const EXTRA_CONTENT_TAB_TITLE = "UPDATES & DLC";
export const EXTRA_CONTENT_PROMPT_TITLE = "Updates & DLC";
export const DOWNLOAD_LABEL = "Download";
export const CANCEL_LABEL = "Cancel";
export const REMOVE_LABEL = "Remove";
export const ON_DEVICE_LABEL = "On this device";
export const ON_ROMM_LABEL = "On RomM";
export const DOWNLOADING_LABEL = "Downloading...";
export const NOT_INSTALLED_LINE = "Download the game to bring these with it; the download asks which.";
export const NOT_READ_FROM_FOLDERS_NOTE =
  "The emulator does not read this file from a folder: a compressed package (.nsz, .xcz) has to be decompressed first.";
export const REMOVE_TITLE = "Remove from this device?";
export const REMOVE_FAILED_TOAST = "Couldn't remove the update or DLC files";
export const DOWNLOAD_FAILED_TOAST = "Couldn't download the update or DLC files";

/** The question a Download asks before it starts, above the list. */
export function promptIntro(romName: string): string {
  return `${romName || "This game"} has updates and DLC on RomM. The game itself always downloads; tick what to bring with it.`;
}

/** What a file is, and how big. */
export function fileDetail(file: ExtraContentFile): string {
  return `${file.category === "update" ? "Update" : "DLC"} · ${formatBytes(file.size_bytes)}`;
}

/** The label of the button that downloads the ticked files. */
export function downloadTickedLabel(count: number): string {
  return count === 1 ? "Download 1 file" : `Download ${count} files`;
}

/** Where the game's folder is not one the emulator scans: add the system's ROM folder as a game folder that is searched to its subfolders. */
export function notScannedNote(romFolder: string | null): string {
  const folder = romFolder ?? "the Switch ROM folder";
  return `The emulator does not look for updates and DLC in this game's folder. In Eden, add ${folder} as a game folder and turn on scanning its subfolders, so it loads them.`;
}

/** The removal's question, naming what goes and that RomM keeps it. */
export function removeDescription(files: ExtraContentFile[]): string {
  const what = files.length === 1 ? (files[0]?.file_name ?? "This file") : `These ${files.length} files`;
  return `${what} will be deleted from this device. RomM keeps them, and you can download them again.`;
}

/** The toast after a download whose update and DLC files did not all arrive. */
export function extraContentMissingToast(romName: string, missing: number): string {
  const what = missing === 1 ? "1 update or DLC file" : `${missing} update or DLC files`;
  return `${what} of ${romName || "the game"} could not be downloaded; try again from the UPDATES & DLC tab.`;
}

/** The toast after a download of extra content alone. */
export function extraContentDownloadedToast(romName: string): string {
  return `Downloaded updates & DLC for ${romName || "the game"}`;
}

/** The toasts a finished download raises: what it brought, and what of the extra content asked for did not arrive. */
export function downloadCompleteToasts(evt: DownloadCompleteEvent): string[] {
  const toasts = [evt.extra_content_only ? extraContentDownloadedToast(evt.rom_name) : `Downloaded ${evt.rom_name}`];
  if (evt.extra_content_missing) toasts.push(extraContentMissingToast(evt.rom_name, evt.extra_content_missing));
  return toasts;
}
