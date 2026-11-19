import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as backend from "../api/backend";
import { applyInstallState, keepInstallStateWritten } from "./installState";

vi.mock("../api/backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/backend")>()),
  debugLog: vi.fn().mockResolvedValue(undefined),
  logWarn: vi.fn(),
}));

// Steam's entry carries more than Tender declares; the extra fields are what
// "leaves other clients alone" and the untouched remainder are checked against.
type ClientData = SteamPerClientData & { client_name: string; is_available_on_current_platform: boolean };

const thisMachine = (): ClientData => ({
  clientid: "0",
  client_name: "",
  display_status: 11,
  status_percentage: 100,
  installed: true,
  is_available_on_current_platform: true,
});

const remoteClient = (): ClientData => ({
  clientid: "714028187146002066",
  client_name: "DESKTOP",
  display_status: 9,
  is_available_on_current_platform: true,
});

function overview(appid: number): SteamAppOverview {
  return { appid, display_name: "", strDisplayName: "", per_client_data: [thisMachine(), remoteClient()] };
}

describe("applyInstallState", () => {
  let overviews: Map<number, SteamAppOverview>;

  beforeEach(() => {
    overviews = new Map([101, 102].map((id) => [id, overview(id)]));
    vi.stubGlobal("appStore", { GetAppOverviewByAppID: (id: number) => overviews.get(id) ?? null });
    vi.mocked(backend.getInstalledAppIds).mockResolvedValue([101]);
    vi.mocked(backend.getAppIdRomIdMap).mockResolvedValue({ "101": 1, "102": 2 });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("gives a downloaded game Steam's installed shape on this machine", async () => {
    const notInstalled: ClientData = {
      clientid: "0",
      client_name: "",
      display_status: 9,
      is_available_on_current_platform: true,
    };
    overviews.get(101)!.per_client_data![0] = notInstalled;

    await applyInstallState();

    expect(overviews.get(101)!.per_client_data![0]).toEqual(thisMachine());
  });

  it("gives a game that is not downloaded Steam's uninstalled shape, and leaves other clients alone", async () => {
    await applyInstallState();

    const [local, remote] = overviews.get(102)!.per_client_data!;
    expect(local).toEqual({
      clientid: "0",
      client_name: "",
      display_status: 9,
      is_available_on_current_platform: true,
    });
    expect(remote).toEqual(remoteClient());
  });

  it("uses the shortcuts it is handed rather than asking for them", async () => {
    await applyInstallState({ tenderAppIds: [102] });

    expect(backend.getAppIdRomIdMap).not.toHaveBeenCalled();
    expect(overviews.get(101)!.per_client_data![0]).toEqual(thisMachine());
    expect(overviews.get(102)!.per_client_data![0]!.installed).toBeUndefined();
  });

  it("waits for a shortcut Steam has not loaded yet", async () => {
    vi.useFakeTimers();
    const late = overview(102);
    overviews.delete(102);

    const done = applyInstallState();
    await vi.advanceTimersByTimeAsync(0);
    overviews.set(102, late);
    await vi.advanceTimersByTimeAsync(1000);
    await done;

    expect(late.per_client_data![0]!.installed).toBeUndefined();
    expect(late.per_client_data![0]!.display_status).toBe(9);
  });

  it("writes nothing where an overview has no entry for this machine", async () => {
    overviews.get(102)!.per_client_data = [remoteClient()];

    await applyInstallState();

    expect(overviews.get(102)!.per_client_data).toEqual([remoteClient()]);
  });

  it("logs and leaves Steam as it is when the backend cannot say", async () => {
    vi.mocked(backend.getInstalledAppIds).mockRejectedValue(new Error("down"));

    await applyInstallState();

    expect(overviews.get(102)!.per_client_data![0]).toEqual(thisMachine());
    expect(backend.debugLog).toHaveBeenCalledWith(expect.stringContaining("down"));
  });
});

describe("keepInstallStateWritten", () => {
  let overviews: Map<number, SteamAppOverview>;

  // What Steam's full overview update does to a shortcut: a new overview, its
  // entry for this machine installed again.
  function steamRebuilds(appid: number): void {
    overviews.set(appid, overview(appid));
  }

  beforeEach(() => {
    vi.useFakeTimers();
    overviews = new Map([101, 102].map((id) => [id, overview(id)]));
    vi.stubGlobal("appStore", {
      GetAppOverviewByAppID: (id: number) => overviews.get(id) ?? null,
      m_mapApps: { set: (id: number, o: SteamAppOverview) => overviews.set(id, o) },
    });
    vi.stubGlobal("collectionStore", { OnAppOverviewChange: vi.fn() });
    vi.mocked(backend.getInstalledAppIds).mockResolvedValue([101]);
    vi.mocked(backend.getAppIdRomIdMap).mockResolvedValue({ "101": 1, "102": 2 });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("puts a fresh copy of only the overviews it wrote in Steam's map and tells the collections", async () => {
    keepInstallStateWritten();
    await applyInstallState();
    steamRebuilds(102);
    const rebuilt = overviews.get(102)!;
    const untouched = overviews.get(101)!;

    await vi.advanceTimersByTimeAsync(30_000);

    expect(overviews.get(102)).not.toBe(rebuilt);
    expect(overviews.get(102)!.per_client_data![0]!.display_status).toBe(9);
    expect(overviews.get(101)).toBe(untouched);
    expect(collectionStore.OnAppOverviewChange).toHaveBeenCalledTimes(1);
    expect(collectionStore.OnAppOverviewChange).toHaveBeenCalledWith([overviews.get(102)], []);
  });

  it("still writes the state, and tells nothing, where Steam's map cannot be reached", async () => {
    vi.stubGlobal("appStore", { GetAppOverviewByAppID: (id: number) => overviews.get(id) ?? null });
    keepInstallStateWritten();
    await applyInstallState();
    steamRebuilds(102);

    await vi.advanceTimersByTimeAsync(30_000);

    expect(overviews.get(102)!.per_client_data![0]!.display_status).toBe(9);
    expect(collectionStore.OnAppOverviewChange).not.toHaveBeenCalled();
  });

  it("tells nothing when every overview already has its state", async () => {
    keepInstallStateWritten();
    await applyInstallState();

    await vi.advanceTimersByTimeAsync(30_000);

    expect(collectionStore.OnAppOverviewChange).not.toHaveBeenCalled();
  });

  it("writes the last install state again once Steam has rebuilt an overview, without asking the backend", async () => {
    keepInstallStateWritten();
    await applyInstallState();
    vi.mocked(backend.getInstalledAppIds).mockClear();
    steamRebuilds(102);

    await vi.advanceTimersByTimeAsync(30_000);

    expect(overviews.get(102)!.per_client_data![0]!.installed).toBeUndefined();
    expect(overviews.get(102)!.per_client_data![0]!.display_status).toBe(9);
    expect(overviews.get(101)!.per_client_data![0]).toEqual(thisMachine());
    expect(backend.getInstalledAppIds).not.toHaveBeenCalled();
  });

  it("writes nothing before an install state has been read", async () => {
    vi.resetModules();
    const fresh = await import("./installState");
    fresh.keepInstallStateWritten();

    await vi.advanceTimersByTimeAsync(30_000);

    expect(overviews.get(102)!.per_client_data![0]).toEqual(thisMachine());
  });
});
