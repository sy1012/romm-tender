/**
 * The Steam collections Tender made, recognised by their Steam id and never by
 * their name (docs/architecture/steam-non-steam-shortcuts.md, "Collection
 * management"). Kept in `settings.json` and replaced there as a whole, so every
 * change goes through one queue: two passes changing the list at once would
 * otherwise each save a copy missing the other's record.
 */

import { getSettings, logWarn, saveSteamCollections } from "../api/backend";
import type { TenderCollectionKind, TenderCollectionRecord } from "../types";
import { foldCollectionName } from "./collectionName";

let loaded: Promise<TenderCollectionRecord[]> | null = null;
let queue: Promise<unknown> = Promise.resolve();

function load(): Promise<TenderCollectionRecord[]> {
  loaded ??= getSettings().then((settings) => [...(settings.steam_collections_by_tender ?? [])]);
  loaded.catch(() => {
    loaded = null;
  });
  return loaded;
}

/** The recorded collections; rejects when they cannot be read, so nothing is taken for Tender's by guess. */
export function tenderCollectionRecords(): Promise<readonly TenderCollectionRecord[]> {
  return queue.then(load);
}

/** The record Tender keeps for the collection of *kind* filed under *key*, compared as Steam compares names. */
export function findRecord(
  records: readonly TenderCollectionRecord[],
  kind: TenderCollectionKind,
  key: string,
): TenderCollectionRecord | undefined {
  const folded = foldCollectionName(key);
  return records.find((record) => record.kind === kind && foldCollectionName(record.key) === folded);
}

/**
 * Change the recorded list, after every change queued before this one. The
 * change holds for the rest of this load whether or not it could be stored;
 * false when it could not, and the next change that is stored carries it.
 */
export function changeTenderCollectionRecords(
  change: (records: readonly TenderCollectionRecord[]) => TenderCollectionRecord[],
): Promise<boolean> {
  const run = queue.then(async () => {
    const records = await load();
    const next = change(records);
    records.splice(0, records.length, ...next);
    try {
      const result = await saveSteamCollections(next);
      if (result.success) return true;
      logWarn(`The Steam collections Tender made were not recorded: ${result.message ?? result.reason ?? ""}`);
    } catch (e) {
      logWarn(`The Steam collections Tender made were not recorded: ${e}`);
    }
    return false;
  });
  queue = run.catch(() => undefined);
  return run;
}
