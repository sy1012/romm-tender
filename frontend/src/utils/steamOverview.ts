/**
 * The reach into a live `SteamAppOverview` — Steam's own MobX-observed object,
 * looked up in Steam's own appStore.
 *
 * Only what the write touches lives here; what DECIDES which appId gets which
 * value, which items are still pending and when to stop retrying is
 * `metadataPatches.ts`, which reads the overview only through this module. The
 * seam is the object, not the judgement: the three guards below — the rating
 * only where the server sent one, rounded; the categories only where the
 * overview offers the setter; the timestamp only where the caller asked for it
 * — are Tender's decisions rather than Steam's, so each is asserted in
 * both directions through its caller in `metadataPatches.test.ts` rather than
 * exempted. The timestamp is the pair worth stating: a single-app write stamps
 * `rt_last_time_played` because a session has just ended, a bulk pass must not
 * because it is no evidence the game was played, and only the caller knows
 * which it is.
 */
import type { RomMetadata } from "../types";
import { stateTransaction } from "./steamState";

/**
 * Steam's overview object for an app, or `null` when its appStore holds no
 * entry for that appId. Steam rebuilds appStore on every mount and may still be
 * loading shortcuts, so the callers treat a `null` as a "not yet" and retry —
 * but it is also what a shortcut deleted through Steam's own UI answers, and
 * that one never comes back: the binding it was reached through survives in the
 * backend's appId map until the next sync-start reconcile (see
 * `docs/architecture/steam-non-steam-shortcuts.md`). So the retry ladder's
 * "still unavailable after all retries" covers both, and this function cannot
 * tell them apart.
 */
export function overviewFor(appId: number): SteamAppOverview | null {
  return appStore.GetAppOverviewByAppID(appId);
}

/**
 * Write the metadata fields Steam's own UI reads — controller support, the
 * rating it shows as a metacritic score, and the store categories. Idempotent:
 * every write is an assignment or a set-insert of the same value.
 */
export function writeMetadataFields(overview: SteamAppOverview, metadata: RomMetadata): void {
  stateTransaction(() => {
    overview.controller_support = 2;

    if (metadata.average_rating != null) {
      overview.metacritic_score = Math.round(metadata.average_rating);
    }

    if (overview.m_setStoreCategories && metadata.steam_categories) {
      for (const cat of metadata.steam_categories) {
        overview.m_setStoreCategories.add(cat);
      }
    }
  });
}

// The `display_status` Steam gives "This machine" for an installed app and for
// one that is not, read off real Steam games on the reference Deck: an
// installed one also carries `installed: true` and `status_percentage: 100`,
// an uninstalled one neither.
const DISPLAY_STATUS_INSTALLED = 11;
const DISPLAY_STATUS_NOT_INSTALLED = 9;
const THIS_MACHINE = "0";

/**
 * Whether this machine's entry in the overview already has the shape
 * {@link writeInstallState} would give it; `true` for an overview with no such
 * entry, which that write leaves alone.
 */
export function hasInstallState(overview: SteamAppOverview, installed: boolean): boolean {
  const local = overview.per_client_data?.find((entry) => entry.clientid === THIS_MACHINE);
  return !local || hasInstallShape(local, installed);
}

function hasInstallShape(local: SteamPerClientData, installed: boolean): boolean {
  return installed
    ? local.installed === true && local.status_percentage === 100 && local.display_status === DISPLAY_STATUS_INSTALLED
    : local.installed === undefined &&
        local.status_percentage === undefined &&
        local.display_status === DISPLAY_STATUS_NOT_INSTALLED;
}

/**
 * Give this machine's entry in the overview's `per_client_data` the shape Steam
 * gives an installed app, or an uninstalled one — which is what Steam's own
 * Installed filters and `appOverview.installed` read. Other clients' entries
 * are left alone, and an overview with no entry for this machine, or one whose
 * entry already has the shape, is not written. Answers whether it wrote.
 */
export function writeInstallState(overview: SteamAppOverview, installed: boolean): boolean {
  const local = overview.per_client_data?.find((entry) => entry.clientid === THIS_MACHINE);
  if (!local) return false;
  if (hasInstallShape(local, installed)) return false;
  stateTransaction(() => {
    if (installed) {
      local.installed = true;
      local.status_percentage = 100;
      local.display_status = DISPLAY_STATUS_INSTALLED;
    } else {
      delete local.installed;
      delete local.status_percentage;
      local.display_status = DISPLAY_STATUS_NOT_INSTALLED;
    }
  });
  return true;
}

/**
 * Put a fresh copy of each overview in appStore's map and tell the collections
 * they changed, as Steam does for a change of its own (its custom sort name
 * copies the overview with `Object.assign`, sets it in `m_mapApps`, and its
 * overview update tells `collectionStore.OnAppOverviewChange` — read in
 * `sp.js`). Overviews are not observable themselves, so a field written into
 * one is seen only by what reads it next; a filtered tab, TabMaster's among
 * them, keeps its result until the map changes (measured on a Deck: one copy
 * set made the whole Installed tab filter again). Answers how many were set.
 */
export function republishOverviews(appIds: readonly number[]): number {
  const apps = appStore.m_mapApps;
  if (typeof apps?.set !== "function") return 0;
  const copies: SteamAppOverview[] = [];
  for (const appId of appIds) {
    const overview = overviewFor(appId);
    if (!overview) continue;
    const Overview = overview.constructor as new () => SteamAppOverview;
    const copy = Object.assign(new Overview(), overview);
    apps.set(appId, copy);
    copies.push(copy);
  }
  if (copies.length > 0) collectionStore.OnAppOverviewChange?.(copies, []);
  return copies.length;
}

/** What the overview held before {@link writePlaytimeFields} changed it. */
export interface PreviousPlaytime {
  minutes: number | undefined;
  lastPlayed: number | undefined;
}

/**
 * Write tracked playtime into the fields Steam's library shows, so a RomM
 * shortcut reads as played rather than "Never Played". A `null`
 * *totalMinutes* leaves the minutes as Steam shows them. Returns what the two
 * fields held beforehand, which is what the caller's debug line reports.
 */
export function writePlaytimeFields(
  overview: SteamAppOverview,
  totalMinutes: number | null,
  updateLastPlayed: boolean,
): PreviousPlaytime {
  const previous: PreviousPlaytime = {
    minutes: overview.minutes_playtime_forever,
    lastPlayed: overview.rt_last_time_played,
  };
  stateTransaction(() => {
    if (totalMinutes !== null) {
      overview.minutes_playtime_forever = totalMinutes;
    }
    if (updateLastPlayed) {
      overview.rt_last_time_played = Math.floor(Date.now() / 1000);
    }
  });
  return previous;
}
