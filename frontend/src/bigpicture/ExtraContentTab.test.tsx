import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import { showModal } from "@decky/ui";
import type { ReactElement } from "react";
import { toaster } from "../api/host";
import { downloadExtraContent, removeExtraContent } from "../api/backend";
import { ExtraContentTab, folderNote } from "./ExtraContentTab";
import type { ExtraContentAnswer, ExtraContentFile } from "../types";

interface ConfirmModalProps {
  strTitle?: string;
  strDescription?: string;
  strOKButtonText?: string;
  onOK?: () => void;
  onCancel?: () => void;
}

function lastConfirmModalProps(): ConfirmModalProps {
  const calls = vi.mocked(showModal).mock.calls;
  const el = calls[calls.length - 1]?.[0] as ReactElement<ConfirmModalProps> | undefined;
  if (!el) throw new Error("showModal was not called");
  return el.props;
}

function file(overrides: Partial<ExtraContentFile> = {}): ExtraContentFile {
  return {
    file_id: 12,
    file_name: "Game [v65536].nsp",
    rel_path: "update/Game [v65536].nsp",
    category: "update",
    size_bytes: 2048,
    on_device: false,
    ticked: false,
    read_from_folders: true,
    ...overrides,
  };
}

function answer(overrides: Partial<ExtraContentAnswer> = {}): ExtraContentAnswer {
  return {
    success: true,
    offered: true,
    installed: true,
    files: [file(), file({ file_id: 14, file_name: "Game DLC.nsp", category: "dlc", on_device: true })],
    game_folder_scanned: true,
    only_beside_launch: false,
    rom_folder: "/home/deck/retrodeck/roms/switch",
    ...overrides,
  };
}

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((b) => b.textContent === text);
}

function renderTab(shown: ExtraContentAnswer = answer()) {
  const onChanged = vi.fn();
  const rendered = render(<ExtraContentTab romId={7} answer={shown} onChanged={onChanged} />);
  return { ...rendered, onChanged };
}

describe("ExtraContentTab — the UPDATES & DLC pane", () => {
  beforeEach(() => {
    vi.mocked(showModal).mockClear();
    vi.mocked(downloadExtraContent).mockReset();
    vi.mocked(removeExtraContent).mockReset();
  });

  it("lists each file with its size and whether it is on this device", () => {
    const { container } = renderTab();

    expect(container.textContent).toContain("Game [v65536].nsp");
    expect(container.textContent).toContain("Update · 2.0 KB · On RomM");
    expect(container.textContent).toContain("DLC · 2.0 KB · On this device");
  });

  it("downloads the ticked files alone, and reads the answer again", async () => {
    vi.mocked(downloadExtraContent).mockResolvedValue({ success: true, message: "Download started" });
    const { container, onChanged } = renderTab();

    expect(buttonByText(container, "Download 1 file")).toBeUndefined();
    fireEvent.click(container.querySelector<HTMLInputElement>('[data-testid="toggle-input"]')!);
    fireEvent.click(buttonByText(container, "Download 1 file")!);

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(downloadExtraContent).toHaveBeenCalledWith(7, [12]);
  });

  it("says why a download was refused", async () => {
    vi.mocked(downloadExtraContent).mockResolvedValue({
      success: false,
      reason: "extra_content_occupied",
      message: "Something already lies at /x",
    } as never);
    const { container, onChanged } = renderTab();

    fireEvent.click(container.querySelector<HTMLInputElement>('[data-testid="toggle-input"]')!);
    fireEvent.click(buttonByText(container, "Download 1 file")!);

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(vi.mocked(toaster.toast)).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Something already lies at /x" }),
    );
  });

  it("asks before it removes a file, and removes it on Remove", async () => {
    vi.mocked(removeExtraContent).mockResolvedValue({ success: true, removed: 1, message: "Removed 1 file(s)" });
    const { container, onChanged } = renderTab();

    fireEvent.click(buttonByText(container, "Remove")!);
    const props = lastConfirmModalProps();
    expect(props.strTitle).toBe("Remove from this device?");
    expect(props.strDescription).toBe(
      "Game DLC.nsp will be deleted from this device. RomM keeps them, and you can download them again.",
    );
    expect(removeExtraContent).not.toHaveBeenCalled();
    props.onOK?.();

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(removeExtraContent).toHaveBeenCalledWith(7, [14]);
  });

  it("removes nothing on Cancel", async () => {
    const { container, onChanged } = renderTab();

    fireEvent.click(buttonByText(container, "Remove")!);
    lastConfirmModalProps().onCancel?.();
    await Promise.resolve();

    expect(removeExtraContent).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("toasts a removal that threw, and reads the answer again", async () => {
    vi.mocked(removeExtraContent).mockRejectedValue(new Error("socket closed"));
    const { container, onChanged } = renderTab();

    fireEvent.click(buttonByText(container, "Remove")!);
    lastConfirmModalProps().onOK?.();

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(vi.mocked(toaster.toast)).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Couldn't remove the update or DLC files" }),
    );
  });

  it("offers no action for a game that is not downloaded, and says the download brings them", () => {
    const { container } = renderTab(answer({ installed: false }));

    expect(container.querySelector('[data-testid="extra-content-not-installed"]')).not.toBeNull();
    expect(buttonByText(container, "Remove")).toBeUndefined();
    expect(container.querySelector('[data-testid="toggle-input"]')).toBeNull();
  });

  it("says a compressed package is not read from a folder", () => {
    const { container } = renderTab(answer({ files: [file({ file_name: "Game.nsz", read_from_folders: false })] }));

    expect(container.querySelector('[data-testid="extra-content-not-read"]')?.textContent).toContain(".nsz, .xcz");
  });
});

describe("folderNote — what keeps the emulator from loading the files", () => {
  it("names the ROM folder to add as an external content folder where the game's folder is not scanned", () => {
    expect(folderNote(answer({ game_folder_scanned: false }))).toBe(
      "The emulator does not look for updates and DLC in this game's folder. In Eden's settings, add " +
        "/home/deck/retrodeck/roms/switch as an external content folder so it loads them.",
    );
  });

  it("warns that a launch from Steam may not apply them where the folder is scanned only beside the launch", () => {
    expect(folderNote(answer({ only_beside_launch: true }))).toContain(
      "may not apply them when the game is started from Steam. Add /home/deck/retrodeck/roms/switch as an external content folder",
    );
  });

  it("says nothing where the folder is scanned before the launch, or where that is not established", () => {
    expect(folderNote(answer())).toBeNull();
    expect(folderNote(answer({ game_folder_scanned: null }))).toBeNull();
  });
});
