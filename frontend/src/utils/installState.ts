/**
 * Tell Steam which of Tender's shortcuts are installed, so its own Installed
 * filters — and TabMaster's, which read the same getter — see a game that is
 * not downloaded as not installed. Steam marks every shortcut installed, and
 * rebuilds its overviews on every mount and whenever it sends them again, so
 * this runs on each load, again whenever what is on disk changes, and again
 * after Steam changes its overviews (docs/architecture/steam-non-steam-shortcuts.md,
 * "Install state").
 */

import { debugLog, getAppIdRomIdMap, getInstalledAppIds, logWarn } from "../api/backend";
import { detach } from "./detach";
import { overviewFor, writeInstallState } from "./steamOverview";

// The same readiness ladder as the metadata and playtime passes: appStore may
// not hold the shortcuts yet on a cold boot.
const DELAYS = [0, 1000, 3000, 5000];

// How long after Steam changes its overviews the last state is written again;
// a change that arrives meanwhile is covered by the same write.
const REWRITE_DELAY_MS = 1000;

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
  for (const appId of lastApplied.appIds) {
    const overview = overviewFor(appId);
    if (overview) writeInstallState(overview, lastApplied.installed.has(appId));
  }
}

/**
 * Write the last install state again shortly after every change Steam makes to
 * its overviews: a full update — which Steam sends again after a resume from
 * suspend — rebuilds each overview from Steam's own data and puts every
 * shortcut back to installed. The state written is the one the last
 * {@link applyInstallState} read, so a burst of changes costs no call to the
 * backend. Registered once per load: Steam answers the registration with
 * nothing to take it back by, so it lasts as long as the JavaScript context.
 */
export function rewriteInstallStateOnOverviewChanges(): void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    SteamClient.Apps.RegisterForAppOverviewChanges(() => {
      if (timer !== undefined) return;
      timer = setTimeout(() => {
        timer = undefined;
        rewriteLastApplied();
      }, REWRITE_DELAY_MS);
    });
  } catch (e) {
    logWarn(
      `Steam's overview changes could not be followed, so a game's install state may read as installed until the next sync: ${e}`,
    );
  }
}
