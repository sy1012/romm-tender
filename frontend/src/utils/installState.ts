/**
 * Tell Steam which of Tender's shortcuts are installed, so its own Installed
 * filters — and TabMaster's, which read the same getter — see a game that is
 * not downloaded as not installed. Steam marks every shortcut installed, and
 * rebuilds its overviews on every mount and whenever it sends them again, so
 * this runs on each load, again whenever what is on disk changes, and again
 * whenever Steam has put them back (docs/architecture/steam-non-steam-shortcuts.md,
 * "Install state").
 */

import { debugLog, getAppIdRomIdMap, getInstalledAppIds } from "../api/backend";
import { detach } from "./detach";
import { hasInstallState, overviewFor, republishOverviews, writeInstallState } from "./steamOverview";

// The same readiness ladder as the metadata and playtime passes: appStore may
// not hold the shortcuts yet on a cold boot.
const DELAYS = [0, 1000, 3000, 5000];

// How often the last state is checked against Steam's overviews, behind the map
// observer (docs/architecture/steam-non-steam-shortcuts.md, "Install state").
const KEEP_WRITTEN_MS = 30_000;

// How soon after Steam sets a shortcut back to installed the state is written
// again; a rebuild sets every overview in waves, and each window covers a wave.
const CORRECT_AFTER_MS = 250;

let lastApplied: { installed: ReadonlySet<number>; appIds: readonly number[]; tender: ReadonlySet<number> } | null =
  null;

export async function applyInstallState(options: { tenderAppIds?: readonly number[] } = {}): Promise<void> {
  let installed: Set<number>;
  let pending: number[];
  try {
    const [installedIds, tenderAppIds] = await Promise.all([
      getInstalledAppIds(),
      options.tenderAppIds ?? getAppIdRomIdMap().then((map) => Object.keys(map).map(Number)),
    ]);
    installed = new Set(installedIds);
    pending = [...tenderAppIds];
    lastApplied = { installed, appIds: [...tenderAppIds], tender: new Set(tenderAppIds) };
  } catch (e) {
    detach(debugLog(`applyInstallState: could not read the install state, Steam left as it is: ${e}`));
    return;
  }

  for (const delay of DELAYS) {
    if (pending.length === 0) break;
    if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
    pending = pending.filter((appId) => {
      const overview = overviewFor(appId);
      if (!overview) return true;
      writeInstallState(overview, installed.has(appId));
      return false;
    });
  }
  if (pending.length > 0) {
    detach(debugLog(`applyInstallState: ${pending.length} shortcuts still not in appStore after all retries`));
  }
}

function rewriteLastApplied(): void {
  if (!lastApplied) return;
  const written: number[] = [];
  for (const appId of lastApplied.appIds) {
    const overview = overviewFor(appId);
    if (overview && writeInstallState(overview, lastApplied.installed.has(appId))) written.push(appId);
  }
  if (written.length > 0) republishOverviews(written);
}

/**
 * Check the last install state every {@link KEEP_WRITTEN_MS} and write again
 * any shortcut Steam put back to installed: Steam rebuilds its overviews from
 * its own data on some updates — after a resume from suspend among them — and
 * every shortcut reads as installed again. The state is the one the last
 * {@link applyInstallState} read, so a check costs no call to the backend, and
 * an entry that already has the shape is skipped, so a check normally writes
 * nothing. Started once per load; it lasts as long as the JavaScript context.
 */
export function keepInstallStateWritten(): void {
  setInterval(rewriteLastApplied, KEEP_WRITTEN_MS);
}

let correction: ReturnType<typeof setTimeout> | undefined;

/**
 * Write the install state again within {@link CORRECT_AFTER_MS} of Steam setting
 * one of Tender's shortcuts back to installed, by observing appStore's
 * `m_mapApps` — the observable map Steam's rebuild after a resume sets every
 * overview into. An observer is added beside Steam's own, never in place of
 * them, unlike a `SteamClient.Apps.RegisterFor…` callback. A change that already
 * has its state — Tender's own republished copies among them — is ignored, so
 * the correction does not feed itself. Started once per load, it lasts as long
 * as the JavaScript context; where the map cannot be observed, the periodic
 * check alone keeps the state.
 */
export function correctInstallStateOnRebuild(): void {
  const apps = appStore.m_mapApps;
  if (typeof apps?.observe_ !== "function") {
    detach(
      debugLog(
        "correctInstallStateOnRebuild: Steam's overview map cannot be observed; the periodic check keeps the state",
      ),
    );
    return;
  }
  apps.observe_((change) => {
    if (!lastApplied || correction !== undefined || change.type === "delete") return;
    const appId = Number(change.name);
    const overview = change.newValue;
    if (!lastApplied.tender.has(appId) || !overview) return;
    if (hasInstallState(overview, lastApplied.installed.has(appId))) return;
    correction = setTimeout(() => {
      correction = undefined;
      rewriteLastApplied();
    }, CORRECT_AFTER_MS);
  });
}
