import { describe, expect, it } from "vitest";
import { packageNotInstalledToast } from "./packageInstallWording";

describe("packageNotInstalledToast", () => {
  it("says the licence may be missing where no boot file appeared, and that the download is kept", () => {
    expect(packageNotInstalledToast("Puppeteer", { reason: "no_boot_file", installer: "RPCS3" })).toBe(
      "RPCS3 could not install the package of Puppeteer — the licence may be missing. The downloaded package is kept.",
    );
  });

  it("names each other reason", () => {
    const say = (reason: Parameters<typeof packageNotInstalledToast>[1]["reason"]) =>
      packageNotInstalledToast("Puppeteer", { reason, installer: "RPCS3" });

    expect(say("did_not_finish")).toBe("RPCS3 did not finish installing Puppeteer. The downloaded package is kept.");
    expect(say("not_started")).toBe("RPCS3 could not be started to install Puppeteer. The downloaded package is kept.");
    expect(say("several_games")).toContain("more than one game");
    expect(say("command_incomplete")).toBe(
      "Tender could not tell how RPCS3 installs the package of Puppeteer. The downloaded package is kept.",
    );
  });

  it("names the emulator generically where none was named, and the game where it has no name", () => {
    expect(packageNotInstalledToast("", { reason: "did_not_finish", installer: null })).toBe(
      "The emulator did not finish installing the game. The downloaded package is kept.",
    );
  });
});
