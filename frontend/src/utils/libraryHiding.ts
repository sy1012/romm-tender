/**
 * Hiding synced games from Steam's library: what is hidden, and why only what
 * Tender hid is ever unhidden, is docs/architecture/steam-non-steam-shortcuts.md
 * § Hiding synced games.
 */

import { getAppIdRomIdMap, getSettings, logInfo, logWarn, saveSteamLibraryHiding } from "../api/backend";

/** What one pass changes in Steam, and the appIds Tender has hidden once it has. */
export interface HidingPlan {
  toHide: number[];
  toUnhide: number[];
  hiddenByTender: number[];
}

export function planLibraryHiding(
  enabled: boolean,
  tenderAppIds: readonly number[],
  hiddenByTender: readonly number[],
  isHidden: (appId: number) => boolean,
): HidingPlan {
  const tender = new Set(tenderAppIds);
  if (!enabled) {
    return {
      toHide: [],
      toUnhide: hiddenByTender.filter((appId) => tender.has(appId) && isHidden(appId)),
      hiddenByTender: [],
    };
  }
  const toHide = tenderAppIds.filter((appId) => !isHidden(appId));
  const kept = hiddenByTender.filter((appId) => tender.has(appId));
  return { toHide, toUnhide: [], hiddenByTender: [...new Set([...kept, ...toHide])] };
}

function sameIds(a: readonly number[], b: readonly number[]): boolean {
  return a.length === b.length && a.every((appId, i) => appId === b[i]);
}

/**
 * Bring Steam's Hidden flag on Tender's shortcuts in line with the switch —
 * *enabled*, or the stored one when it is not given. False when nothing could be
 * changed: Steam has no Hidden calls, or the backend refused the record.
 */
export async function applyLibraryHiding(
  options: { enabled?: boolean; tenderAppIds?: readonly number[] } = {},
): Promise<boolean> {
  const store = typeof collectionStore === "undefined" ? undefined : collectionStore;
  const isHidden = store?.BIsHidden?.bind(store);
  const setHidden = store?.SetAppsAsHidden?.bind(store);
  if (!isHidden || !setHidden) {
    logWarn("Steam's Hidden calls are not available, so synced games cannot be hidden");
    return false;
  }

  const [settings, tenderAppIds] = await Promise.all([
    getSettings(),
    options.tenderAppIds ?? getAppIdRomIdMap().then((map) => Object.keys(map).map(Number)),
  ]);
  const storedEnabled = settings.steam_library_hidden ?? false;
  const storedHidden = settings.steam_hidden_by_tender ?? [];
  const enabled = options.enabled ?? storedEnabled;
  const plan = planLibraryHiding(enabled, tenderAppIds, storedHidden, isHidden);

  // Recorded before Steam is changed: a hide Tender made but never recorded is
  // one it could never undo.
  if (enabled !== storedEnabled || !sameIds(plan.hiddenByTender, storedHidden)) {
    const result = await saveSteamLibraryHiding(enabled, plan.hiddenByTender);
    if (!result.success) {
      logWarn(`Synced games' Hidden state was not recorded, so Steam was left as it is: ${result.message}`);
      return false;
    }
  }
  if (plan.toHide.length > 0) setHidden(plan.toHide, true);
  if (plan.toUnhide.length > 0) setHidden(plan.toUnhide, false);
  if (plan.toHide.length + plan.toUnhide.length > 0) {
    logInfo(`Library hiding: hid ${plan.toHide.length}, unhid ${plan.toUnhide.length}`);
  }
  return true;
}
