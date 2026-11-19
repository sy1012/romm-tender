import { describe, it, expect, vi, beforeEach } from "vitest";
import type { TenderCollectionRecord } from "../types";

vi.mock("../api/backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/backend")>()),
  logWarn: vi.fn(),
}));

let backend: typeof import("../api/backend");
let stored: TenderCollectionRecord[];

async function load() {
  vi.resetModules();
  backend = await import("../api/backend");
  vi.mocked(backend.getSettings).mockImplementation(
    async () => ({ steam_collections_by_tender: stored }) as Awaited<ReturnType<typeof backend.getSettings>>,
  );
  vi.mocked(backend.saveSteamCollections).mockImplementation(async (records) => {
    stored = records;
    return { success: true };
  });
  return import("./collectionRecords");
}

const SNES: TenderCollectionRecord = { id: "uc-1", kind: "platform", key: "SNES" };
const FAVES: TenderCollectionRecord = { id: "uc-2", kind: "collection", key: "Faves" };

beforeEach(() => {
  vi.clearAllMocks();
  stored = [];
});

describe("the recorded Steam collections", () => {
  it("keeps both of two changes made at once", async () => {
    const { changeTenderCollectionRecords, tenderCollectionRecords } = await load();

    await Promise.all([
      changeTenderCollectionRecords((records) => [...records, SNES]),
      changeTenderCollectionRecords((records) => [...records, FAVES]),
    ]);

    expect(stored).toEqual([SNES, FAVES]);
    expect(await tenderCollectionRecords()).toEqual([SNES, FAVES]);
  });

  it("holds a change that could not be stored for this load, and stores it with the next one", async () => {
    const { changeTenderCollectionRecords, tenderCollectionRecords } = await load();
    vi.mocked(backend.saveSteamCollections).mockResolvedValueOnce({
      success: false,
      reason: "invalid_value",
      message: "refused",
    });

    expect(await changeTenderCollectionRecords((records) => [...records, SNES])).toBe(false);
    expect(backend.logWarn).toHaveBeenCalledWith(expect.stringContaining("refused"));
    expect(await tenderCollectionRecords()).toEqual([SNES]);

    expect(await changeTenderCollectionRecords((records) => [...records, FAVES])).toBe(true);
    expect(stored).toEqual([SNES, FAVES]);
  });

  it("answers false and logs when the save rejects", async () => {
    const { changeTenderCollectionRecords } = await load();
    vi.mocked(backend.saveSteamCollections).mockRejectedValueOnce(new Error("down"));

    expect(await changeTenderCollectionRecords(() => [SNES])).toBe(false);
    expect(backend.logWarn).toHaveBeenCalledWith(expect.stringContaining("down"));
  });

  it("asks again after a read that failed, rather than taking an empty list", async () => {
    const { tenderCollectionRecords } = await load();
    stored = [SNES];
    vi.mocked(backend.getSettings).mockRejectedValueOnce(new Error("down"));

    await expect(tenderCollectionRecords()).rejects.toThrow("down");
    expect(await tenderCollectionRecords()).toEqual([SNES]);
  });

  it("finds a record by a key that differs only by case, within its own kind", async () => {
    const { findRecord } = await load();

    expect(findRecord([SNES, FAVES], "platform", "snes")).toBe(SNES);
    expect(findRecord([SNES, FAVES], "collection", "SNES")).toBeUndefined();
  });
});
