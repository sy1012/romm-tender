import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { EdenAppImageModal, EdenAppImageRefused } from "./EdenAppImageModal";

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function input(container: HTMLElement): HTMLInputElement {
  const field = container.querySelector("input");
  if (field === null) throw new Error("no field");
  return field;
}

describe("EdenAppImageModal", () => {
  it("is prefilled with the path set", () => {
    const { container } = render(<EdenAppImageModal current="/opt/Eden.AppImage" onSave={vi.fn()} />);
    expect(input(container).value).toBe("/opt/Eden.AppImage");
  });

  it("saves the path entered, trimmed, and closes", async () => {
    const onSave = vi.fn(async () => {});
    const closeModal = vi.fn();
    const { container, getByText } = render(<EdenAppImageModal current="" onSave={onSave} closeModal={closeModal} />);

    fireEvent.change(input(container), { target: { value: "  /home/deck/Applications/Eden.AppImage " } });
    fireEvent.click(getByText("Save"));
    await settle();

    expect(onSave).toHaveBeenCalledWith("/home/deck/Applications/Eden.AppImage");
    expect(closeModal).toHaveBeenCalledTimes(1);
  });

  it("saves an empty field as none set", async () => {
    const onSave = vi.fn(async () => {});
    const { container, getByText } = render(<EdenAppImageModal current="/opt/Eden.AppImage" onSave={onSave} />);

    fireEvent.change(input(container), { target: { value: "" } });
    fireEvent.click(getByText("Save"));
    await settle();

    expect(onSave).toHaveBeenCalledWith("");
  });

  it("stays open with the backend's message where the path is refused", async () => {
    const onSave = vi.fn(async () => {
      throw new EdenAppImageRefused("The Eden AppImage is named by a full path, starting with /.");
    });
    const closeModal = vi.fn();
    const { getByText, getByTestId } = render(
      <EdenAppImageModal current="Eden.AppImage" onSave={onSave} closeModal={closeModal} />,
    );

    fireEvent.click(getByText("Save"));
    await settle();

    expect(getByTestId("eden-appimage-error")).toHaveTextContent(
      "The Eden AppImage is named by a full path, starting with /.",
    );
    expect(closeModal).not.toHaveBeenCalled();
  });

  it("says the save failed where it threw for another reason", async () => {
    const onSave = vi.fn(async () => {
      throw new Error("socket closed");
    });
    const { getByText, getByTestId } = render(<EdenAppImageModal current="/opt/Eden.AppImage" onSave={onSave} />);

    fireEvent.click(getByText("Save"));
    await settle();

    expect(getByTestId("eden-appimage-error")).toHaveTextContent("The path could not be saved. Try again.");
  });
});
