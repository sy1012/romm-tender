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
import { overviewFor, republishOverviews, writeInstallState } from "./steamOverview";

// The same readiness ladder as the metadata and playtime passes: appStore may
// not hold the shortcuts yet on a cold boot.
const DELAYS = [0, 1000, 3000, 5000];

// How often the last state is checked against Steam's overviews. A poll, never a
// listener on Steam's overview changes — why is
// docs/architecture/steam-non-steam-shortcuts.md, "Install state".
const KEEP_WRITTEN_MS = 30_000;

let lastApplied: { installed: ReadonlySet<number>; appIds: readonly number[] } | null = null;

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
    lastApplied = { installed, appIds: [...tenderAppIds] };
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
