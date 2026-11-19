import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import type { TenderCollectionRecord } from "../types";

vi.mock("../api/backend", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/backend")>()),
  logInfo: vi.fn(),
  logWarn: vi.fn(),
  logError: vi.fn(),
}));

// Tender knows its collections by the ids recorded in settings.json; the
// host is "test".

interface FakeDnd {
  RemoveApps: ReturnType<typeof vi.fn>;
  AddApps: ReturnType<typeof vi.fn>;
}
interface FakeCollection {
  id: string;
  displayName: string;
  allApps: unknown[];
  AsDragDropCollection: () => FakeDnd;
  Save: Mock<() => Promise<void>>;
  Delete: Mock<() => Promise<void>>;
  dnd: FakeDnd;
}

let nextId = 0;

function fakeCollection(displayName: string, id = `uc-${++nextId}`): FakeCollection {
  const dnd: FakeDnd = { RemoveApps: vi.fn(), AddApps: vi.fn() };
  return {
    id,
    displayName,
    allApps: [],
    AsDragDropCollection: () => dnd,
    Save: vi.fn(() => Promise.resolve()),
    Delete: vi.fn(() => Promise.resolve()),
    dnd,
  };
}

let stored: TenderCollectionRecord[];
let userCollections: FakeCollection[];
const NewUnsavedCollection = vi.fn((name: string) => {
  const created = fakeCollection(name);
  created.Save.mockImplementation(() => {
    userCollections.push(created);
    return Promise.resolve();
  });
  return created;
});

let backend: typeof import("../api/backend");

/** A fresh load of the module, as each Steam start is: nothing recorded or adopted is carried in memory. */
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
  return import("./collections");
}

beforeEach(() => {
  vi.clearAllMocks();
  nextId = 0;
  stored = [];
  userCollections = [];
  vi.stubGlobal("SteamClient", { System: { GetSystemInfo: vi.fn().mockResolvedValue({ sHostname: "test" }) } });
  vi.stubGlobal("collectionStore", {
    get userCollections() {
      return userCollections;
    },
    NewUnsavedCollection,
  });
});

describe("a platform or RomM collection", () => {
  it("is made under the platform's own name, and its id is recorded before Steam saves it", async () => {
    const { createOrUpdateCollections } = await load();
    vi.mocked(backend.saveSteamCollections).mockImplementation(async (records) => {
      expect(userCollections).toEqual([]);
      stored = records;
      return { success: true };
    });

    const nameTaken = await createOrUpdateCollections({ "Game Boy Advance": [1001, 1002] });

    expect(nameTaken).toEqual([]);
    expect(NewUnsavedCollection).toHaveBeenCalledWith("Game Boy Advance", undefined, []);
    expect(userCollections.map((c) => c.displayName)).toEqual(["Game Boy Advance"]);
    expect(stored).toEqual([{ id: userCollections[0]!.id, kind: "platform", key: "Game Boy Advance" }]);
  });

  it("is made under the RomM collection's key, with no prefix or host", async () => {
    const { createOrUpdateRomMCollections } = await load();

    await createOrUpdateRomMCollections({ "Mario (Franchise)": [1] });

    expect(NewUnsavedCollection).toHaveBeenCalledWith("Mario (Franchise)", undefined, []);
    expect(stored).toEqual([{ id: userCollections[0]!.id, kind: "collection", key: "Mario (Franchise)" }]);
  });

  it("is updated by its recorded id, whatever it is named now", async () => {
    const renamed = fakeCollection("My handhelds", "uc-gba");
    userCollections = [renamed];
    stored = [{ id: "uc-gba", kind: "platform", key: "Game Boy Advance" }];
    const { createOrUpdateCollections } = await load();

    await createOrUpdateCollections({ "Game Boy Advance": [1001] });

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(renamed.dnd.AddApps).toHaveBeenCalledWith([expect.objectContaining({ appid: 1001 })]);
    expect(renamed.Save).toHaveBeenCalledTimes(1);
  });

  it("is found by a key that differs only by case, as Steam compares names (#1569)", async () => {
    const mine = fakeCollection("7 Up", "uc-7");
    userCollections = [mine];
    stored = [{ id: "uc-7", kind: "collection", key: "7 Up" }];
    const { createOrUpdateRomMCollections } = await load();

    await createOrUpdateRomMCollections({ "7 UP": [1] });

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(mine.Save).toHaveBeenCalledTimes(1);
  });

  it("is not made beside another collection holding its name in another case, which is left alone", async () => {
    const theirs = fakeCollection("GAME BOY ADVANCE");
    userCollections = [theirs];
    const { createOrUpdateCollections } = await load();

    const nameTaken = await createOrUpdateCollections({ "Game Boy Advance": [1001], N64: [2001] });

    expect(nameTaken).toEqual(["Game Boy Advance"]);
    expect(NewUnsavedCollection).toHaveBeenCalledTimes(1);
    expect(NewUnsavedCollection).toHaveBeenCalledWith("N64", undefined, []);
    expect(theirs.dnd.AddApps).not.toHaveBeenCalled();
    expect(theirs.Save).not.toHaveBeenCalled();
    expect(stored.map((record) => record.key)).toEqual(["N64"]);
  });

  it("is not made under a name another of Tender's collections already holds", async () => {
    const platform = fakeCollection("Arcade", "uc-arcade");
    userCollections = [platform];
    stored = [{ id: "uc-arcade", kind: "platform", key: "Arcade" }];
    const { createOrUpdateRomMCollections } = await load();

    expect(await createOrUpdateRomMCollections({ Arcade: [1] })).toEqual(["Arcade"]);
    expect(platform.Save).not.toHaveBeenCalled();
  });

  it("is made again when the one recorded is gone from Steam, and the old record forgotten", async () => {
    stored = [{ id: "uc-deleted", kind: "platform", key: "N64" }];
    const { createOrUpdateCollections } = await load();

    await createOrUpdateCollections({ N64: [1] });

    expect(NewUnsavedCollection).toHaveBeenCalledTimes(1);
    expect(stored).toEqual([{ id: userCollections[0]!.id, kind: "platform", key: "N64" }]);
  });

  it("does not begin another collection mutation after cancellation", async () => {
    let settle!: () => void;
    const first = fakeCollection("First", "uc-first");
    first.Save.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        settle = resolve;
      }),
    );
    const second = fakeCollection("Second", "uc-second");
    userCollections = [first, second];
    stored = [
      { id: "uc-first", kind: "platform", key: "First" },
      { id: "uc-second", kind: "platform", key: "Second" },
    ];
    const { createOrUpdateCollections } = await load();
    const controller = new AbortController();
    const applying = createOrUpdateCollections({ First: [1], Second: [2] }, undefined, controller.signal);
    await vi.waitFor(() => expect(first.Save).toHaveBeenCalled());

    controller.abort();
    settle();
    await applying;

    expect(second.dnd.AddApps).not.toHaveBeenCalled();
    expect(second.Save).not.toHaveBeenCalled();
  });

  it("is left alone, with nothing made, when the recorded ids cannot be read", async () => {
    const { createOrUpdateCollections } = await load();
    vi.mocked(backend.getSettings).mockRejectedValue(new Error("down"));

    await createOrUpdateCollections({ N64: [1] });

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(backend.logError).toHaveBeenCalledWith(expect.stringContaining("down"));
  });
});

describe("the synced-games collection", () => {
  it("is made as RomM (host) holding every synced game, and recorded", async () => {
    const { saveSyncedGamesCollection } = await load();

    expect(await saveSyncedGamesCollection([1001, 1002])).toEqual([]);

    expect(NewUnsavedCollection).toHaveBeenCalledWith("RomM (test)", undefined, []);
    expect(userCollections[0]!.dnd.AddApps).toHaveBeenCalledWith([
      expect.objectContaining({ appid: 1001 }),
      expect.objectContaining({ appid: 1002 }),
    ]);
    expect(stored).toEqual([{ id: userCollections[0]!.id, kind: "synced", key: "" }]);
  });

  it("updates the recorded one instead of making a second", async () => {
    const existing = fakeCollection("RomM (old-name)", "uc-synced");
    userCollections = [existing];
    stored = [{ id: "uc-synced", kind: "synced", key: "" }];
    const { saveSyncedGamesCollection } = await load();

    await saveSyncedGamesCollection([1001]);

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(existing.Save).toHaveBeenCalledTimes(1);
  });

  it("is not written with no synced games", async () => {
    const { saveSyncedGamesCollection } = await load();

    await saveSyncedGamesCollection([]);

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
  });
});

describe("removing Tender's collections", () => {
  it("clears a platform's recorded collection, and never one merely named like it", async () => {
    const mine = fakeCollection("Game Boy", "uc-gb");
    const theirs = fakeCollection("game boy");
    userCollections = [mine, theirs];
    stored = [{ id: "uc-gb", kind: "platform", key: "Game Boy" }];
    const { clearPlatformCollection } = await load();

    await clearPlatformCollection("GAME BOY");

    expect(mine.Delete).toHaveBeenCalledTimes(1);
    expect(theirs.Delete).not.toHaveBeenCalled();
    expect(stored).toEqual([]);
  });

  it("deletes only a recorded platform or RomM collection the run no longer names", async () => {
    const kept = fakeCollection("N64", "uc-n64");
    const gone = fakeCollection("Dreamcast", "uc-dc");
    const goneCollection = fakeCollection("Old Faves", "uc-faves");
    const synced = fakeCollection("RomM (test)", "uc-synced");
    const theirs = fakeCollection("Saturn");
    userCollections = [kept, gone, goneCollection, synced, theirs];
    stored = [
      { id: "uc-n64", kind: "platform", key: "N64" },
      { id: "uc-dc", kind: "platform", key: "Dreamcast" },
      { id: "uc-faves", kind: "collection", key: "Old Faves" },
      { id: "uc-synced", kind: "synced", key: "" },
    ];
    const { removeStaleCollections } = await load();

    await removeStaleCollections(["n64"], []);

    expect([kept, gone, goneCollection, synced, theirs].map((c) => c.Delete.mock.calls.length)).toEqual([
      0, 1, 1, 0, 0,
    ]);
    expect(stored.map((record) => record.id)).toEqual(["uc-n64", "uc-synced"]);
  });

  it("clears every recorded collection and nothing else, then forgets them", async () => {
    const platform = fakeCollection("SNES", "uc-snes");
    const synced = fakeCollection("RomM (test)", "uc-synced");
    const lookalike = fakeCollection("RomM: [Faves] (othermachine)");
    const theirs = fakeCollection("Favourites");
    userCollections = [platform, synced, lookalike, theirs];
    stored = [
      { id: "uc-snes", kind: "platform", key: "SNES" },
      { id: "uc-synced", kind: "synced", key: "" },
      { id: "uc-gone", kind: "collection", key: "Gone" },
    ];
    const { clearAllRomMCollections } = await load();

    await clearAllRomMCollections();

    expect([platform, synced, lookalike, theirs].map((c) => c.Delete.mock.calls.length)).toEqual([1, 1, 0, 0]);
    expect(stored).toEqual([]);
  });
});

describe("collections an earlier version named after the host", () => {
  it("are renamed to their plain key and recorded, and another host's are left alone", async () => {
    const platform = fakeCollection("RomM: Game Boy Advance (test)", "uc-gba");
    const collection = fakeCollection("ROMM: [Faves] (TEST)", "uc-faves");
    const synced = fakeCollection("RomM (test)", "uc-synced");
    const otherHost = fakeCollection("RomM: N64 (othermachine)", "uc-other");
    userCollections = [platform, collection, synced, otherHost];
    const { adoptLegacyCollections } = await load();

    expect(await adoptLegacyCollections()).toEqual([]);

    expect([platform, collection, synced, otherHost].map((c) => c.displayName)).toEqual([
      "Game Boy Advance",
      "Faves",
      "RomM (test)",
      "RomM: N64 (othermachine)",
    ]);
    expect(platform.Save).toHaveBeenCalledTimes(1);
    expect(synced.Save).not.toHaveBeenCalled();
    expect(otherHost.Save).not.toHaveBeenCalled();
    expect(stored).toEqual([
      { id: "uc-gba", kind: "platform", key: "Game Boy Advance" },
      { id: "uc-faves", kind: "collection", key: "Faves" },
      { id: "uc-synced", kind: "synced", key: "" },
    ]);
  });

  it("keeps its old name where another collection holds the plain one, says so, and is still updated by id", async () => {
    const old = fakeCollection("RomM: N64 (test)", "uc-n64");
    const theirs = fakeCollection("n64");
    userCollections = [old, theirs];
    const { adoptLegacyCollections, createOrUpdateCollections } = await load();

    expect(await adoptLegacyCollections()).toEqual(["RomM: N64 (test)"]);
    expect(old.displayName).toBe("RomM: N64 (test)");
    expect(old.Save).not.toHaveBeenCalled();
    expect(stored).toEqual([{ id: "uc-n64", kind: "platform", key: "N64" }]);

    expect(await createOrUpdateCollections({ N64: [1] })).toEqual([]);
    expect(old.Save).toHaveBeenCalledTimes(1);
    expect(theirs.Save).not.toHaveBeenCalled();
  });

  it("are adopted before a sync writes, so no plain-named collection is made beside the old one", async () => {
    const old = fakeCollection("RomM: SNES (test)", "uc-snes");
    userCollections = [old];
    const { createOrUpdateCollections } = await load();

    await createOrUpdateCollections({ SNES: [1] });

    expect(NewUnsavedCollection).not.toHaveBeenCalled();
    expect(old.displayName).toBe("SNES");
    expect(stored).toEqual([{ id: "uc-snes", kind: "platform", key: "SNES" }]);
  });

  it("are not adopted again once recorded", async () => {
    const old = fakeCollection("RomM: N64 (test)", "uc-n64");
    userCollections = [old, fakeCollection("N64")];
    stored = [{ id: "uc-n64", kind: "platform", key: "N64" }];
    const { adoptLegacyCollections } = await load();

    expect(await adoptLegacyCollections()).toEqual([]);
    expect(backend.saveSteamCollections).not.toHaveBeenCalled();
  });
});

describe("tenderCollectionIds", () => {
  it("answers the recorded ids, not names that look like Tender's", async () => {
    userCollections = [fakeCollection("RomM: [Faves] (othermachine)", "uc-x")];
    stored = [{ id: "uc-1", kind: "platform", key: "SNES" }];
    const { tenderCollectionIds } = await load();

    expect(await tenderCollectionIds()).toEqual(new Set(["uc-1"]));
  });
});

describe("the notices", () => {
  it("name every collection Tender left alone", async () => {
    const { nameTakenMessage, keptOldNameMessage } = await load();

    expect(nameTakenMessage(["N64"])).toContain('"N64"');
    expect(nameTakenMessage(["N64", "SNES"])).toContain('"N64", "SNES"');
    expect(keptOldNameMessage(["RomM: N64 (deck)"])).toContain('"RomM: N64 (deck)"');
  });
});
