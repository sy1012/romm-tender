import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as backend from "../api/backend";
import type { Settings } from "../types";
import { applyLibraryHiding, planLibraryHiding } from "./libraryHiding";

vi.mock("../api/backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/backend")>()),
  logInfo: vi.fn(),
  logWarn: vi.fn(),
}));

const hiddenAmong = (ids: number[]) => (appId: number) => ids.includes(appId);

describe("planLibraryHiding", () => {
  it("hides every Tender shortcut that is not hidden yet and records only those", () => {
    const plan = planLibraryHiding(true, [1, 2, 3], [], hiddenAmong([2]));
    expect(plan.toHide).toEqual([1, 3]);
    expect(plan.toUnhide).toEqual([]);
    expect(plan.hiddenByTender).toEqual([1, 3]);
  });

  it("keeps what Tender hid before and drops a shortcut that is no longer Tender's", () => {
    const plan = planLibraryHiding(true, [1, 2], [1, 9], hiddenAmong([1]));
    expect(plan.toHide).toEqual([2]);
    expect(plan.hiddenByTender).toEqual([1, 2]);
  });

  it("switched off, unhides only what Tender hid and forgets the list", () => {
    // 2 was hidden by the user, never by Tender: it stays hidden.
    const plan = planLibraryHiding(false, [1, 2, 3], [1, 3], hiddenAmong([1, 2, 3]));
    expect(plan.toHide).toEqual([]);
    expect(plan.toUnhide).toEqual([1, 3]);
    expect(plan.hiddenByTender).toEqual([]);
  });

  it("switched off, leaves alone a recorded shortcut that is already visible or no longer Tender's", () => {
    const plan = planLibraryHiding(false, [1, 2], [1, 2, 9], hiddenAmong([2, 9]));
    expect(plan.toUnhide).toEqual([2]);
  });
});

describe("applyLibraryHiding", () => {
  let hidden: Set<number>;
  let SetAppsAsHidden: ReturnType<typeof vi.fn>;

  function stored(steam_library_hidden: boolean, steam_hidden_by_tender: number[]): void {
    vi.mocked(backend.getSettings).mockResolvedValue({ steam_library_hidden, steam_hidden_by_tender } as Settings);
  }

  beforeEach(() => {
    hidden = new Set();
    SetAppsAsHidden = vi.fn((ids: number[], value: boolean) => {
      for (const id of ids) {
        if (value) hidden.add(id);
        else hidden.delete(id);
      }
    });
    vi.stubGlobal("collectionStore", { BIsHidden: (id: number) => hidden.has(id), SetAppsAsHidden });
    vi.mocked(backend.getAppIdRomIdMap).mockResolvedValue({ "11": 1, "12": 2 });
    vi.mocked(backend.saveSteamLibraryHiding).mockResolvedValue({ success: true });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("records the hides before it makes them, so a failed record leaves Steam untouched", async () => {
    stored(false, []);
    vi.mocked(backend.saveSteamLibraryHiding).mockResolvedValue({
      success: false,
      reason: "invalid_value",
      message: "no",
    });

    expect(await applyLibraryHiding({ enabled: true })).toBe(false);

    expect(backend.saveSteamLibraryHiding).toHaveBeenCalledWith(true, [11, 12]);
    expect(SetAppsAsHidden).not.toHaveBeenCalled();
    expect(backend.logWarn).toHaveBeenCalledWith(expect.stringContaining("no"));
  });

  it("switched on, hides the synced games and records them", async () => {
    stored(false, []);

    expect(await applyLibraryHiding({ enabled: true })).toBe(true);

    expect(SetAppsAsHidden).toHaveBeenCalledWith([11, 12], true);
    expect(backend.saveSteamLibraryHiding).toHaveBeenCalledWith(true, [11, 12]);
  });

  it("switched off, unhides what it hid and leaves the user's own hide", async () => {
    stored(true, [11]);
    hidden = new Set([11, 12]);

    await applyLibraryHiding({ enabled: false });

    expect(SetAppsAsHidden).toHaveBeenCalledWith([11], false);
    expect([...hidden]).toEqual([12]);
    expect(backend.saveSteamLibraryHiding).toHaveBeenCalledWith(false, []);
  });

  it("with no switch given, follows the stored one and hides a newly synced game", async () => {
    stored(true, [11]);
    hidden = new Set([11]);

    await applyLibraryHiding();

    expect(SetAppsAsHidden).toHaveBeenCalledWith([12], true);
    expect(backend.saveSteamLibraryHiding).toHaveBeenCalledWith(true, [11, 12]);
  });

  it("writes nothing when nothing changes", async () => {
    stored(false, []);

    expect(await applyLibraryHiding()).toBe(true);

    expect(SetAppsAsHidden).not.toHaveBeenCalled();
    expect(backend.saveSteamLibraryHiding).not.toHaveBeenCalled();
  });

  it("uses the shortcuts it is handed rather than asking again", async () => {
    stored(true, []);

    await applyLibraryHiding({ tenderAppIds: [12] });

    expect(backend.getAppIdRomIdMap).not.toHaveBeenCalled();
    expect(SetAppsAsHidden).toHaveBeenCalledWith([12], true);
  });

  it("does nothing, and says so, where Steam has no Hidden calls", async () => {
    vi.stubGlobal("collectionStore", {});
    stored(true, []);

    expect(await applyLibraryHiding({ enabled: true })).toBe(false);

    expect(backend.saveSteamLibraryHiding).not.toHaveBeenCalled();
    expect(backend.logWarn).toHaveBeenCalledWith(expect.stringContaining("Hidden"));
  });
});
