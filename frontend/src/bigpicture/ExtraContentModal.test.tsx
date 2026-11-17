import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { ExtraContentModal } from "./ExtraContentModal";
import type { ExtraContentFile } from "../types";

function file(overrides: Partial<ExtraContentFile> = {}): ExtraContentFile {
  return {
    file_id: 12,
    file_name: "Game [v65536].nsp",
    rel_path: "update/Game [v65536].nsp",
    category: "update",
    size_bytes: 300 * 1024 * 1024,
    on_device: false,
    ticked: false,
    read_from_folders: true,
    ...overrides,
  };
}

const FILES = [
  file(),
  file({ file_id: 13, file_name: "Game [v131072].nsp", ticked: true }),
  file({ file_id: 14, file_name: "Game DLC.nsp", category: "dlc", size_bytes: 1024, ticked: true }),
];

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === text);
  if (!btn) throw new Error(`button "${text}" not found`);
  return btn as HTMLButtonElement;
}

function checkboxes(container: HTMLElement): HTMLInputElement[] {
  return Array.from(container.querySelectorAll<HTMLInputElement>('[data-testid="toggle-input"]'));
}

function renderModal(files: ExtraContentFile[] = FILES) {
  const onAnswer = vi.fn();
  const closeModal = vi.fn();
  const rendered = render(
    <ExtraContentModal romName="Zelda" files={files} closeModal={closeModal} onAnswer={onAnswer} />,
  );
  return { ...rendered, onAnswer, closeModal };
}

describe("ExtraContentModal — the question a Download asks", () => {
  it("lists every update and DLC file with what it is and its size, and says the game always downloads", () => {
    const { container } = renderModal();

    expect(container.textContent).toContain("Zelda has updates and DLC on RomM. The game itself always downloads");
    expect(container.textContent).toContain("Game [v65536].nsp");
    expect(container.textContent).toContain("Update · 300.0 MB");
    expect(container.textContent).toContain("DLC · 1.0 KB");
  });

  it("comes with the newest update and every DLC file ticked, as the answer says", () => {
    const { container } = renderModal();

    expect(checkboxes(container).map((box) => box.checked)).toEqual([false, true, true]);
  });

  it("answers the ticked ids on Download, in the list's order", () => {
    const { container, onAnswer, closeModal } = renderModal();

    fireEvent.click(buttonByText(container, "Download"));

    expect(onAnswer).toHaveBeenCalledWith([13, 14]);
    expect(closeModal).toHaveBeenCalled();
  });

  it("answers what the user ticked and unticked", () => {
    const { container, onAnswer } = renderModal();
    const [older, newer] = checkboxes(container);

    fireEvent.click(older!);
    fireEvent.click(newer!);
    fireEvent.click(buttonByText(container, "Download"));

    expect(onAnswer).toHaveBeenCalledWith([12, 14]);
  });

  it("answers an empty list where nothing is ticked: the game downloads alone", () => {
    const { container, onAnswer } = renderModal([file()]);

    fireEvent.click(buttonByText(container, "Download"));

    expect(onAnswer).toHaveBeenCalledWith([]);
  });

  it("answers null on Cancel, which cancels the download", () => {
    const { container, onAnswer } = renderModal();

    fireEvent.click(buttonByText(container, "Cancel"));

    expect(onAnswer).toHaveBeenCalledWith(null);
  });

  it("says where the emulator does not read a file from a folder", () => {
    const { container } = renderModal([file({ file_name: "Game [v1].nsz", read_from_folders: false })]);

    expect(container.textContent).toContain("compressed package (.nsz, .xcz) has to be decompressed first");
  });
});
