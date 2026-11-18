import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { getExtraContent } from "../api/backend";
import { emitHostEvent, hostEventListenerCount } from "../test-utils/host-event-bus";
import { askExtraContent, showsExtraContent, useExtraContent } from "./extraContent";
import { downloadCompleteToasts } from "./extraContentWording";
import type { DownloadCompleteEvent, ExtraContentAnswer } from "../types";

const OFFERED: ExtraContentAnswer = {
  success: true,
  offered: true,
  installed: false,
  files: [
    {
      file_id: 14,
      file_name: "Game DLC.nsp",
      rel_path: "dlc/Game DLC.nsp",
      category: "dlc",
      size_bytes: 10,
      on_device: false,
      ticked: true,
      read_from_folders: true,
    },
  ],
  game_folder_scanned: true,
  rom_folder: "/roms/switch",
};
const NOT_OFFERED: ExtraContentAnswer = { ...OFFERED, offered: false, files: [] };

const COMPLETE: DownloadCompleteEvent = { rom_id: 7, rom_name: "Zelda", platform_name: "Switch", file_path: "/x" };

describe("askExtraContent — the question a Download asks first", () => {
  beforeEach(() => {
    vi.mocked(getExtraContent).mockReset();
  });

  it("asks where extra content is offered, and answers what was ticked", async () => {
    vi.mocked(getExtraContent).mockResolvedValue(OFFERED);
    const ask = vi.fn().mockResolvedValue([14]);

    await expect(askExtraContent(7, "Zelda", ask)).resolves.toEqual([14]);
    expect(ask).toHaveBeenCalledWith("Zelda", OFFERED);
  });

  it("answers null where the user cancelled", async () => {
    vi.mocked(getExtraContent).mockResolvedValue(OFFERED);

    await expect(askExtraContent(7, "Zelda", vi.fn().mockResolvedValue(null))).resolves.toBeNull();
  });

  it("asks nothing where nothing is offered", async () => {
    vi.mocked(getExtraContent).mockResolvedValue(NOT_OFFERED);
    const ask = vi.fn();

    await expect(askExtraContent(7, "Zelda", ask)).resolves.toBeUndefined();
    expect(ask).not.toHaveBeenCalled();
  });

  it("asks nothing where the answer is a refusal", async () => {
    vi.mocked(getExtraContent).mockResolvedValue({ success: false, reason: "not_found", message: "no" });
    const ask = vi.fn();

    await expect(askExtraContent(7, "Zelda", ask)).resolves.toBeUndefined();
    expect(ask).not.toHaveBeenCalled();
  });

  it("downloads the game alone where the question could not be read", async () => {
    vi.mocked(getExtraContent).mockImplementation(() => Promise.reject(new Error("socket closed")));
    const ask = vi.fn();

    await expect(askExtraContent(7, "Zelda", ask)).resolves.toBeUndefined();
    expect(ask).not.toHaveBeenCalled();
  });
});

describe("showsExtraContent", () => {
  it("shows the tab only where extra content is offered and RomM holds some", () => {
    expect(showsExtraContent(OFFERED)).toBe(true);
    expect(showsExtraContent(NOT_OFFERED)).toBe(false);
    expect(showsExtraContent({ ...OFFERED, files: [] })).toBe(false);
    expect(showsExtraContent(null)).toBe(false);
  });
});

describe("useExtraContent", () => {
  beforeEach(() => {
    vi.mocked(getExtraContent).mockReset();
  });

  it("reads the answer, and again when a download of the game ends", async () => {
    vi.mocked(getExtraContent).mockResolvedValue(OFFERED);
    const { result } = renderHook(() => useExtraContent(7, false));

    await waitFor(() => expect(result.current.answer).toEqual(OFFERED));
    act(() => emitHostEvent<DownloadCompleteEvent>("download_complete", { ...COMPLETE, rom_id: 8 }));
    expect(getExtraContent).toHaveBeenCalledTimes(1);
    act(() => emitHostEvent<DownloadCompleteEvent>("download_complete", COMPLETE));

    await waitFor(() => expect(getExtraContent).toHaveBeenCalledTimes(2));
  });

  it("holds no answer where the read fails", async () => {
    vi.mocked(getExtraContent).mockImplementation(() => Promise.reject(new Error("socket closed")));
    const { result } = renderHook(() => useExtraContent(7, false));

    await waitFor(() => expect(getExtraContent).toHaveBeenCalled());
    expect(result.current.answer).toBeNull();
  });

  it("stops listening once unmounted", () => {
    vi.mocked(getExtraContent).mockResolvedValue(OFFERED);
    const { unmount } = renderHook(() => useExtraContent(7, false));

    unmount();

    expect(hostEventListenerCount("download_complete")).toBe(0);
    expect(hostEventListenerCount("download_failed")).toBe(0);
  });
});

describe("downloadCompleteToasts", () => {
  it("names the game a download brought", () => {
    expect(downloadCompleteToasts(COMPLETE)).toEqual(["Downloaded Zelda"]);
  });

  it("names a download of extra content alone as such", () => {
    expect(downloadCompleteToasts({ ...COMPLETE, extra_content_only: true })).toEqual([
      "Downloaded updates & DLC for Zelda",
    ]);
  });

  it("says how many update and DLC files did not arrive", () => {
    expect(downloadCompleteToasts({ ...COMPLETE, extra_content_missing: 2 })).toEqual([
      "Downloaded Zelda",
      "2 update or DLC files of Zelda could not be downloaded; try again from the UPDATES & DLC tab.",
    ]);
  });

  it("says why a downloaded package was not installed into its emulator", () => {
    expect(
      downloadCompleteToasts({ ...COMPLETE, package_not_installed: { reason: "no_boot_file", installer: "RPCS3" } }),
    ).toEqual([
      "Downloaded Zelda",
      "RPCS3 could not install the package of Zelda — the licence may be missing. The downloaded package is kept.",
    ]);
  });
});
