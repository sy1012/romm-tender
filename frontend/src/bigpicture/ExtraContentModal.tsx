/**
 * The question a Download asks of a game with updates and DLC on RomM, where
 * its emulator loads them from folders: a checklist of every update and DLC
 * file with its size. The newest update and every DLC file come ticked
 * (`ticked`, the backend's rule); the game itself always downloads. Cancel
 * cancels the download.
 */

import { FC, useState } from "react";
import { DialogButton, ModalRoot, ToggleField, showModal } from "@decky/ui";
import type { ExtraContentAnswer, ExtraContentFile } from "../types";
import {
  CANCEL_LABEL,
  DOWNLOAD_LABEL,
  EXTRA_CONTENT_PROMPT_TITLE,
  NOT_READ_FROM_FOLDERS_NOTE,
  fileDetail,
  promptIntro,
} from "../utils/extraContentWording";

interface ExtraContentModalProps {
  romName: string;
  files: ExtraContentFile[];
  closeModal?: () => void;
  /** The ids ticked on Download, `null` on Cancel. */
  onAnswer: (ticked: number[] | null) => void;
}

/** One file's second line: what it is and how big, and that the emulator does not read it from a folder where so. */
function description(file: ExtraContentFile): string {
  return file.read_from_folders === false ? `${fileDetail(file)} — ${NOT_READ_FROM_FOLDERS_NOTE}` : fileDetail(file);
}

export const ExtraContentModal: FC<ExtraContentModalProps> = ({ romName, files, closeModal, onAnswer }) => {
  const [ticked, setTicked] = useState<Set<number>>(
    () => new Set(files.filter((file) => file.ticked).map((file) => file.file_id)),
  );
  const answer = (value: number[] | null) => {
    closeModal?.();
    onAnswer(value);
  };
  const toggle = (fileId: number, on: boolean) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(fileId);
      else next.delete(fileId);
      return next;
    });

  return (
    <ModalRoot closeModal={() => answer(null)}>
      <div style={{ padding: "16px", minWidth: "420px" }}>
        <div style={{ fontSize: "16px", fontWeight: "bold", color: "#fff", marginBottom: "4px" }}>
          {EXTRA_CONTENT_PROMPT_TITLE}
        </div>
        <div style={{ fontSize: "13px", color: "rgba(255,255,255,0.7)", marginBottom: "12px" }}>
          {promptIntro(romName)}
        </div>
        <div data-testid="extra-content-checklist" style={{ marginBottom: "12px" }}>
          {files.map((file) => (
            <ToggleField
              key={file.file_id}
              label={file.file_name}
              description={description(file)}
              checked={ticked.has(file.file_id)}
              onChange={(on: boolean) => toggle(file.file_id, on)}
            />
          ))}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <DialogButton onClick={() => answer(files.map((f) => f.file_id).filter((id) => ticked.has(id)))}>
            {DOWNLOAD_LABEL}
          </DialogButton>
          <DialogButton onClick={() => answer(null)} style={{ opacity: 0.5 }}>
            {CANCEL_LABEL}
          </DialogButton>
        </div>
      </div>
    </ModalRoot>
  );
};

/**
 * Ask which of *answer*'s files a download brings. Resolves with the ids ticked
 * on Download — perhaps none — and `null` on Cancel or a dismissal.
 */
export function showExtraContentModal(romName: string, answer: ExtraContentAnswer): Promise<number[] | null> {
  return new Promise<number[] | null>((resolve) => {
    showModal(<ExtraContentModal romName={romName} files={answer.files} onAnswer={resolve} />);
  });
}
