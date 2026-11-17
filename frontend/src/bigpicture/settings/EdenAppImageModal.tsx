/**
 * Prompt for the Eden AppImage Tender starts Switch games with, prefilled with
 * the one set. Save stores the path the field holds, and an empty field sets
 * none, so Tender searches again; a path the backend refuses keeps the modal
 * open with the backend's message. ``onSave`` owns the backend call.
 */

import { FC, useState, ChangeEvent } from "react";
import { TextField, Focusable } from "@decky/ui";
import { ValidatingModalShell } from "./ValidatingModalShell";
import { EDEN_APPIMAGE_SEARCH } from "../../utils/emulatorSourceWording";

interface EdenAppImageModalProps {
  closeModal?: () => void;
  /** The path set now, `""` for none. */
  current: string;
  /** Stores *path*; throws {@link EdenAppImageRefused} with the backend's message where it is refused. */
  onSave: (path: string) => Promise<void>;
}

/** What ``onSave`` throws when the backend refused the path; the modal shows its message. */
export class EdenAppImageRefused extends Error {}

const GENERIC_SAVE_ERROR = "The path could not be saved. Try again.";

const helperTextStyle = { fontSize: "12px", marginBottom: "12px", color: "rgba(255,255,255,0.6)" } as const;

export const EdenAppImageModal: FC<EdenAppImageModalProps> = ({ closeModal, current, onSave }) => {
  const [value, setValue] = useState(current);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSave(value.trim());
      closeModal?.();
    } catch (e) {
      setError(e instanceof EdenAppImageRefused ? e.message : GENERIC_SAVE_ERROR);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ValidatingModalShell
      {...(closeModal === undefined ? {} : { closeModal })}
      title="Eden AppImage"
      error={error}
      errorTestId="eden-appimage-error"
      submitLabel={submitting ? "Saving…" : "Save"}
      submitting={submitting}
      submitDisabled={submitting}
      dialogOKSubmits={true}
      onSubmit={() => {
        void submit();
      }}
    >
      <div style={helperTextStyle}>
        The full path of the Eden AppImage to start Switch games with, starting with /. Leave it empty and Tender{" "}
        {EDEN_APPIMAGE_SEARCH}
      </div>
      {/* Wrapped in <Focusable> as SgdbApiKeyModal's field is, for the same reason. */}
      <Focusable>
        <TextField
          focusOnMount={true}
          label="Path"
          value={value}
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            setValue(e.target.value);
            setError(null);
          }}
        />
      </Focusable>
    </ValidatingModalShell>
  );
};
