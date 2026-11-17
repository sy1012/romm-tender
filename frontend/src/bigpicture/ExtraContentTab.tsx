/**
 * ExtraContentTab — the UPDATES & DLC pane: every update and DLC file RomM
 * holds for the game, with its size and whether it is on this device.
 *
 * For an installed game the files not on the device can be ticked and
 * downloaded, alone or together, without touching the game's own files, and
 * a file on the device can be removed — after a confirmation, since it is
 * deleted here though RomM keeps it. Above the list stands what keeps the
 * emulator from loading them, where something does: the game's folder outside
 * every folder it scans, or scanned only while the game starts.
 *
 * Shown only where the panel's answer offers extra content
 * (`showsExtraContent`); the answer and its re-reads are the panel's.
 */

import { FC, useState, type ReactElement } from "react";
import { ConfirmModal, DialogButton, Focusable, Toggle, showModal } from "@decky/ui";
import { downloadExtraContent, removeExtraContent } from "../api/backend";
import type { ExtraContentAnswer, ExtraContentFile } from "../types";
import { detach } from "../utils/detach";
import { showToast } from "../utils/toast";
import {
  DOWNLOADING_LABEL,
  DOWNLOAD_FAILED_TOAST,
  NOT_INSTALLED_LINE,
  NOT_READ_FROM_FOLDERS_NOTE,
  ON_DEVICE_LABEL,
  ON_ROMM_LABEL,
  REMOVE_FAILED_TOAST,
  REMOVE_LABEL,
  REMOVE_TITLE,
  downloadTickedLabel,
  fileDetail,
  notScannedNote,
  removeDescription,
} from "../utils/extraContentWording";

interface ExtraContentTabProps {
  romId: number;
  answer: ExtraContentAnswer;
  /** Reads the answer again, once a download has started or a removal has ended. */
  onChanged: () => void;
}

const NOTE_STYLE = { fontSize: "12px", color: "#ffaa00", padding: "0 0 10px" };
const MUTED_STYLE = { fontSize: "12px" };

/** What stands in the way of the emulator loading the files, where something does. */
export function folderNote(answer: ExtraContentAnswer): string | null {
  if (answer.game_folder_scanned === false) return notScannedNote(answer.rom_folder);
  return null;
}

/** Ask before a removal; resolves `true` on Remove. */
function confirmRemoval(files: ExtraContentFile[]): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    showModal(
      <ConfirmModal
        strTitle={REMOVE_TITLE}
        strDescription={removeDescription(files)}
        strOKButtonText={REMOVE_LABEL}
        strCancelButtonText="Cancel"
        onOK={() => resolve(true)}
        onCancel={() => resolve(false)}
      />,
    );
  });
}

export const ExtraContentTab: FC<ExtraContentTabProps> = ({ romId, answer, onChanged }) => {
  const [ticked, setTicked] = useState<Set<number>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const note = folderNote(answer);
  const wanted = answer.files.filter((file) => !file.on_device && ticked.has(file.file_id));

  const toggle = (fileId: number, on: boolean) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(fileId);
      else next.delete(fileId);
      return next;
    });

  const download = async () => {
    setBusy(true);
    try {
      const result = await downloadExtraContent(
        romId,
        wanted.map((file) => file.file_id),
      );
      if (!result.success) showToast(result.message || DOWNLOAD_FAILED_TOAST);
      else setTicked(new Set());
    } catch {
      showToast(DOWNLOAD_FAILED_TOAST);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  const remove = async (file: ExtraContentFile) => {
    if (!(await confirmRemoval([file]))) return;
    setBusy(true);
    try {
      const result = await removeExtraContent(romId, [file.file_id]);
      if (!result.success) showToast(result.message || REMOVE_FAILED_TOAST);
    } catch {
      showToast(REMOVE_FAILED_TOAST);
    } finally {
      setBusy(false);
      onChanged();
    }
  };

  const row = (file: ExtraContentFile): ReactElement => (
    <Focusable
      key={file.file_id}
      data-testid={`extra-content-row-${file.file_id}`}
      flow-children="row"
      style={{ display: "flex", alignItems: "center", gap: "12px", padding: "6px 0" }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "13px", color: "#fff", overflowWrap: "anywhere" }}>{file.file_name}</div>
        <div className="romm-panel-muted" style={MUTED_STYLE}>
          {`${fileDetail(file)} · ${file.on_device ? ON_DEVICE_LABEL : ON_ROMM_LABEL}`}
        </div>
        {file.read_from_folders === false ? (
          <div data-testid="extra-content-not-read" style={{ ...NOTE_STYLE, padding: "2px 0 0" }}>
            {NOT_READ_FROM_FOLDERS_NOTE}
          </div>
        ) : null}
      </div>
      {!answer.installed ? null : file.on_device ? (
        <DialogButton style={{ width: "auto", minWidth: "96px" }} disabled={busy} onClick={() => detach(remove(file))}>
          {REMOVE_LABEL}
        </DialogButton>
      ) : (
        <Toggle value={ticked.has(file.file_id)} disabled={busy} onChange={(on: boolean) => toggle(file.file_id, on)} />
      )}
    </Focusable>
  );

  return (
    <div data-testid="extra-content-tab">
      {note === null ? null : (
        <div data-testid="extra-content-folder-note" style={NOTE_STYLE}>
          {note}
        </div>
      )}
      {answer.installed ? null : (
        <div
          data-testid="extra-content-not-installed"
          className="romm-panel-muted"
          style={{ ...MUTED_STYLE, padding: "0 0 10px" }}
        >
          {NOT_INSTALLED_LINE}
        </div>
      )}
      {answer.files.map(row)}
      {answer.installed && wanted.length > 0 ? (
        <DialogButton style={{ marginTop: "10px" }} disabled={busy} onClick={() => detach(download())}>
          {busy ? DOWNLOADING_LABEL : downloadTickedLabel(wanted.length)}
        </DialogButton>
      ) : null}
    </div>
  );
};
