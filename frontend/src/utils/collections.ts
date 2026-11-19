/**
 * Steam collection management for RomM platforms and collections, through
 * Steam's own collectionStore. Which collections are Tender's, how each is
 * named, and what happens beside one Tender did not make is
 * docs/architecture/steam-non-steam-shortcuts.md, "Collection management".
 */

import { logInfo, logWarn, logError } from "../api/backend";
import type { TenderCollectionKind, TenderCollectionRecord } from "../types";
import { foldCollectionName } from "./collectionName";
import { changeTenderCollectionRecords, findRecord, tenderCollectionRecords } from "./collectionRecords";

let _hostname = "";

export async function getHostname(): Promise<string> {
  if (_hostname) return _hostname;
  try {
    const info = await SteamClient.System.GetSystemInfo();
    _hostname = info.sHostname || "unknown";
  } catch {
    _hostname = "unknown";
  }
  return _hostname;
}

function getOverviews(appIds: readonly number[]): SteamAppOverview[] {
  const overviews: SteamAppOverview[] = [];
  for (const appId of appIds) {
    if (typeof appStore !== "undefined") {
      const overview = appStore.GetAppOverviewByAppID(appId);
      if (overview) {
        overviews.push(overview);
        continue;
      }
    }
    // Fallback: construct a minimal overview
    overviews.push({ appid: appId, display_name: "", strDisplayName: "" });
  }
  return overviews;
}

function collectionById(id: string): SteamCollection | undefined {
  return collectionStore.userCollections.find((collection) => collection.id === id);
}

function collectionNamed(name: string): SteamCollection | undefined {
  const target = foldCollectionName(name);
  return collectionStore.userCollections.find((collection) => foldCollectionName(collection.displayName) === target);
}

function syncedGamesCollectionName(hostname: string): string {
  return `RomM (${hostname})`;
}

// What earlier versions named this host's collections: "RomM: <platform> (<host>)"
// and "RomM: [<collection>] (<host>)".
const HOST_SCOPED_NAME = /^RomM: (.+) \(([^()]+)\)$/i;
const BRACKETED_KEY = /^\[([^\]]+)\]$/;

function legacyRecordFor(displayName: string, hostname: string): Omit<TenderCollectionRecord, "id"> | null {
  if (foldCollectionName(displayName) === foldCollectionName(syncedGamesCollectionName(hostname))) {
    return { kind: "synced", key: "" };
  }
  const match = HOST_SCOPED_NAME.exec(displayName);
  if (!match || foldCollectionName(match[2]!) !== foldCollectionName(hostname)) return null;
  const bracketed = BRACKETED_KEY.exec(match[1]!);
  return bracketed ? { kind: "collection", key: bracketed[1]! } : { kind: "platform", key: match[1]! };
}

// How long, and how often, start-up waits for Steam to load its collections.
const STORE_LOAD_POLL_MS = 1000;
const STORE_LOAD_TIMEOUT_MS = 60_000;

/**
 * Resolve once Steam has loaded its collections from storage. Steam's
 * `userCollections` is a MobX computed over `m_mapCollectionsFromStorage`, which
 * does not exist until that load: read before it, the computed throws inside
 * Steam's own reaction and the library page fails to render for the rest of the
 * session (seen on a Deck at panel load). So the map is checked, never the
 * computed, and a store that does not load in time rejects.
 */
async function collectionStoreLoaded(): Promise<void> {
  for (let waited = 0; ; waited += STORE_LOAD_POLL_MS) {
    if (collectionStore.m_mapCollectionsFromStorage !== undefined) return;
    if (waited >= STORE_LOAD_TIMEOUT_MS) throw new Error("Steam has not loaded its collections");
    await new Promise((resolve) => setTimeout(resolve, STORE_LOAD_POLL_MS));
  }
}

/**
 * Record this host's collections an earlier version named after the host, and
 * give each its plain name where no other collection holds it. Answers the old
 * names kept because another collection holds the plain one.
 */
async function adoptHostScopedCollections(): Promise<string[]> {
  if (typeof collectionStore === "undefined") return [];
  await collectionStoreLoaded();
  const hostname = await getHostname();
  const records = await tenderCollectionRecords();
  const recordedIds = new Set(records.map((record) => record.id));
  const adopted: TenderCollectionRecord[] = [];
  const keptOldName: string[] = [];

  for (const collection of [...collectionStore.userCollections]) {
    if (recordedIds.has(collection.id)) continue;
    const legacy = legacyRecordFor(collection.displayName, hostname);
    if (!legacy) continue;
    if (findRecord([...records, ...adopted], legacy.kind, legacy.key)) continue;
    adopted.push({ id: collection.id, ...legacy });
    if (legacy.kind === "synced") continue;

    const holder = collectionNamed(legacy.key);
    if (holder && holder !== collection) {
      logWarn(`Kept the collection "${collection.displayName}" under its old name: "${holder.displayName}" exists`);
      keptOldName.push(collection.displayName);
      continue;
    }
    const oldName = collection.displayName;
    try {
      collection.displayName = legacy.key;
      await collection.Save();
      logInfo(`Renamed the collection "${oldName}" to "${legacy.key}"`);
    } catch (e) {
      collection.displayName = oldName;
      logError(`Failed to rename the collection "${oldName}": ${e}`);
    }
  }

  if (adopted.length > 0) {
    await changeTenderCollectionRecords((current) => [...current, ...adopted]);
  }
  return keptOldName;
}

let adoption: Promise<string[]> | null = null;

/**
 * Adopt this host's collections from an earlier version, once per load; every
 * collection write waits for it, so no plain-named collection is made beside
 * the one it would have renamed.
 */
export function adoptLegacyCollections(): Promise<string[]> {
  adoption ??= adoptHostScopedCollections();
  adoption.catch(() => {
    adoption = null;
  });
  return adoption;
}

/** The Steam ids of the collections Tender made. */
export async function tenderCollectionIds(): Promise<Set<string>> {
  await adoptLegacyCollections();
  return new Set((await tenderCollectionRecords()).map((record) => record.id));
}

/**
 * Replace an existing collection's apps. Returns false when the signal aborted
 * mid-write, so the caller stops the whole run instead of moving to the next
 * collection.
 */
async function replaceCollectionApps(
  existing: SteamCollection,
  overviews: SteamAppOverview[],
  signal?: AbortSignal,
): Promise<boolean> {
  const existingApps = existing.allApps;
  if (existingApps.length > 0) {
    if (signal?.aborted) return false;
    existing.AsDragDropCollection().RemoveApps(existingApps);
  }
  if (signal?.aborted) return false;
  existing.AsDragDropCollection().AddApps(overviews);
  if (signal?.aborted) return false;
  await existing.Save();
  return true;
}

/** What writing one collection came to. */
type SaveOutcome = "saved" | "aborted" | "nameTaken";

/**
 * Point Tender's collection of *kind* filed under *key* at exactly *overviews*,
 * making it under *name* when Tender has none. Another collection that holds
 * *name* is left alone, and nothing is made beside it: Steam's
 * `SaveCollection` deletes every collection sharing a new one's name.
 */
async function saveTenderCollection(
  kind: TenderCollectionKind,
  key: string,
  name: string,
  noun: string,
  overviews: SteamAppOverview[],
  signal?: AbortSignal,
): Promise<SaveOutcome> {
  const record = findRecord(await tenderCollectionRecords(), kind, key);
  const existing = record ? collectionById(record.id) : undefined;
  if (record && !existing) {
    await changeTenderCollectionRecords((current) => current.filter((entry) => entry.id !== record.id));
  }

  if (existing) {
    logInfo(`Updating ${noun} "${existing.displayName}" with ${overviews.length} apps`);
    if (!(await replaceCollectionApps(existing, overviews, signal))) return "aborted";
  } else {
    const holder = collectionNamed(name);
    if (holder) {
      logWarn(`Left the collection "${holder.displayName}" alone: it is not this one of Tender's`);
      return "nameTaken";
    }
    logInfo(`Creating ${noun} "${name}" with ${overviews.length} apps`);
    const collection = collectionStore.NewUnsavedCollection(name, undefined, []);
    if (signal?.aborted) return "aborted";
    collection.AsDragDropCollection().AddApps(overviews);
    if (signal?.aborted) return "aborted";
    // Steam gives the collection its id when it is made, so it is recorded
    // before it is saved: a collection saved but never recorded would read as
    // one Tender did not make, and block its own name from then on.
    await changeTenderCollectionRecords((current) => [...current, { id: collection.id, kind, key }]);
    await collection.Save();
  }
  return "saved";
}

/**
 * Write one family of collections, reporting progress per entry. A failure on
 * one collection is logged and the rest still run; an abort stops the run.
 * Answers the names another collection holds.
 */
async function saveCollectionFamily(
  kind: TenderCollectionKind,
  entries: Array<[string, number[]]>,
  noun: string,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<string[]> {
  const nameTaken: string[] = [];
  let idx = 0;
  for (const [key, appIds] of entries) {
    if (signal?.aborted) break;
    idx++;
    onProgress?.(idx, entries.length, key);
    try {
      const outcome = await saveTenderCollection(kind, key, key, noun, getOverviews(appIds), signal);
      if (outcome === "aborted") break;
      if (outcome === "nameTaken") nameTaken.push(key);
    } catch (colErr) {
      logError(`Failed to save ${noun} "${key}": ${colErr}`);
    }
  }
  return nameTaken;
}

/**
 * Point Tender's synced-games collection — "RomM (hostname)" when it is made —
 * at every synced game. It is never renamed or deleted by a sync, so a library
 * tab built on it keeps working (docs/architecture/steam-non-steam-shortcuts.md
 * § Hiding synced games). Answers the name when another collection holds it.
 */
export async function saveSyncedGamesCollection(appIds: readonly number[], signal?: AbortSignal): Promise<string[]> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, skipping the synced-games collection");
      return [];
    }
    if (appIds.length === 0) return [];
    await adoptLegacyCollections();
    const name = syncedGamesCollectionName(await getHostname());
    if (signal?.aborted) return [];
    const outcome = await saveTenderCollection("synced", "", name, "collection", getOverviews(appIds), signal);
    return outcome === "nameTaken" ? [name] : [];
  } catch (e) {
    logError(`Failed to update the synced-games collection: ${e}`);
    return [];
  }
}

async function saveFamily(
  kind: TenderCollectionKind,
  keyAppIds: Record<string, number[]>,
  noun: string,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<string[]> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn(`collectionStore not available, skipping ${noun}s`);
      return [];
    }
    await adoptLegacyCollections();
    if (signal?.aborted) return [];
    logInfo(`Creating/updating ${noun}s: ${Object.keys(keyAppIds).join(", ")}`);
    return await saveCollectionFamily(kind, Object.entries(keyAppIds), noun, onProgress, signal);
  } catch (e) {
    logError(`Failed to update ${noun}s: ${e}`);
    return [];
  }
}

/** One collection per platform, named after it. Answers the names another collection holds. */
export function createOrUpdateCollections(
  platformAppIds: Record<string, number[]>,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<string[]> {
  return saveFamily("platform", platformAppIds, "collection", onProgress, signal);
}

/** One collection per RomM collection key, named by it. Answers the names another collection holds. */
export function createOrUpdateRomMCollections(
  collectionAppIds: Record<string, number[]>,
  onProgress?: (current: number, total: number, name: string) => void,
  signal?: AbortSignal,
): Promise<string[]> {
  return saveFamily("collection", collectionAppIds, "RomM collection", onProgress, signal);
}

/** Delete the collections of *records* that Steam still holds, then forget them. False once aborted. */
async function deleteRecorded(records: readonly TenderCollectionRecord[], signal?: AbortSignal): Promise<boolean> {
  const forgotten = new Set<string>();
  let finished = true;
  for (const record of records) {
    if (signal?.aborted) {
      finished = false;
      break;
    }
    const collection = collectionById(record.id);
    if (collection) {
      logInfo(`Deleting collection "${collection.displayName}" (id=${collection.id})`);
      await collection.Delete();
    }
    forgotten.add(record.id);
  }
  if (forgotten.size > 0) {
    await changeTenderCollectionRecords((current) => current.filter((record) => !forgotten.has(record.id)));
  }
  return finished;
}

export async function clearPlatformCollection(platformName: string, signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, cannot clear platform collection");
      return;
    }
    await adoptLegacyCollections();
    if (signal?.aborted) return;
    const record = findRecord(await tenderCollectionRecords(), "platform", platformName);
    if (!record) {
      logInfo(`Collection for "${platformName}" not found, nothing to clear`);
      return;
    }
    await deleteRecorded([record], signal);
  } catch (e) {
    logError(`Failed to clear platform collection: ${e}`);
  }
}

/**
 * Delete Tender's platform and RomM collections whose source the run no longer
 * names. Only a collection Tender recorded is ever deleted.
 */
export async function removeStaleCollections(
  activePlatformNames: readonly string[],
  activeCollectionNames: readonly string[],
  signal?: AbortSignal,
): Promise<void> {
  if (typeof collectionStore === "undefined") return;
  await adoptLegacyCollections();
  if (signal?.aborted) return;
  const active: Record<TenderCollectionKind, Set<string> | null> = {
    platform: new Set(activePlatformNames.map(foldCollectionName)),
    collection: new Set(activeCollectionNames.map(foldCollectionName)),
    synced: null,
  };
  const stale = (await tenderCollectionRecords()).filter((record) => {
    const names = active[record.kind];
    return names !== null && !names.has(foldCollectionName(record.key));
  });
  for (const record of stale) logInfo(`Removing stale collection for "${record.key}" (${record.kind})`);
  await deleteRecorded(stale, signal);
}

/** Delete every collection Tender recorded, and nothing else. */
export async function clearAllRomMCollections(signal?: AbortSignal): Promise<void> {
  try {
    if (typeof collectionStore === "undefined") {
      logWarn("collectionStore not available, cannot clear collections");
      return;
    }
    await adoptLegacyCollections();
    if (signal?.aborted) return;
    const records = await tenderCollectionRecords();
    logInfo(`Deleting ${records.length} collections Tender made`);
    await deleteRecorded([...records], signal);
  } catch (e) {
    logError(`Failed to clear collections: ${e}`);
  }
}

/** What the user is told about collections Tender left alone because another collection holds the name. */
export function nameTakenMessage(names: readonly string[]): string {
  const quoted = names.map((name) => `"${name}"`).join(", ");
  return names.length === 1
    ? `Steam already has another collection named ${quoted}, so Tender left it alone and filed no games there.`
    : `Steam already has other collections named ${quoted}, so Tender left them alone and filed no games there.`;
}

/** What the user is told about Tender's own collections that kept their old name. */
export function keptOldNameMessage(names: readonly string[]): string {
  const quoted = names.map((name) => `"${name}"`).join(", ");
  return `Kept the old name of ${quoted}: Steam already has another collection under the new name.`;
}
