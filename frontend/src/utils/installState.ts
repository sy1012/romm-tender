/**
 * Tell Steam which of Tender's shortcuts are installed, so its own Installed
 * filters — and TabMaster's, which read the same getter — see a game that is
 * not downloaded as not installed. Steam marks every shortcut installed, and
 * rebuilds its overviews on every mount, so this runs on each load and again
 * whenever what is on disk changes (docs/architecture/steam-non-steam-shortcuts.md,
 * "Install state").
 */

import { debugLog, getAppIdRomIdMap, getInstalledAppIds } from "../api/backend";
import { detach } from "./detach";
import { overviewFor, writeInstallState } from "./steamOverview";

// The same readiness ladder as the metadata and playtime passes: appStore may
// not hold the shortcuts yet on a cold boot.
const DELAYS = [0, 1000, 3000, 5000];

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
