/**
 * A game's extra content as the panel holds it: the backend's answer
 * (`getExtraContent`), read again whenever a download or a removal may have
 * changed what is on the device, and the question a Download asks before it
 * starts.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { addEventListener, removeEventListener } from "../api/host";
import { debugLog, getExtraContent } from "../api/backend";
import { detach } from "./detach";
import type { DownloadCompleteEvent, DownloadFailedEvent, ExtraContentAnswer } from "../types";

/** The answer, `null` while none is held or where it could not be read. */
export interface ExtraContentState {
  answer: ExtraContentAnswer | null;
  reload: () => void;
}

/** The answer, where it is one: a refusal or a stubbed call reads as none. */
function asAnswer(result: unknown): ExtraContentAnswer | null {
  if (result == null || typeof result !== "object") return null;
  const answer = result as Partial<ExtraContentAnswer>;
  return answer.success === true && Array.isArray(answer.files) ? (answer as ExtraContentAnswer) : null;
}

/** Whether *answer* gives the game an UPDATES & DLC tab: offered, with a file on RomM to show. */
export function showsExtraContent(answer: ExtraContentAnswer | null): answer is ExtraContentAnswer {
  return answer !== null && answer.offered && answer.files.length > 0;
}

/**
 * The extra content of *romId*, read when the game or its install state
 * changes and again on every download of it that ends.
 */
export function useExtraContent(romId: number | null, installed: boolean): ExtraContentState {
  // Held with the game it is about, so a switch to another game shows none until its own arrives.
  const [held, setHeld] = useState<{ romId: number; answer: ExtraContentAnswer | null } | null>(null);
  const seq = useRef(0);

  const reload = useCallback(() => {
    if (romId === null) return;
    const ticket = ++seq.current;
    detach(
      Promise.resolve()
        .then(() => getExtraContent(romId))
        .then((result) => {
          if (ticket === seq.current) setHeld({ romId, answer: asAnswer(result) });
        })
        .catch((e: unknown) => {
          if (ticket === seq.current) setHeld({ romId, answer: null });
          detach(debugLog(`extra content: read of rom ${romId} failed: ${e}`));
        }),
    );
  }, [romId]);

  useEffect(() => {
    reload();
  }, [reload, installed]);

  useEffect(() => {
    if (romId === null) return undefined;
    const complete = addEventListener<DownloadCompleteEvent>("download_complete", (evt) => {
      if (evt.rom_id === romId) reload();
    });
    const failed = addEventListener<DownloadFailedEvent>("download_failed", (evt) => {
      if (evt.rom_id === romId) reload();
    });
    return () => {
      removeEventListener("download_complete", complete);
      removeEventListener("download_failed", failed);
    };
  }, [romId, reload]);

  return { answer: held !== null && held.romId === romId ? held.answer : null, reload };
}

/**
 * Ask which of a game's update and DLC files a Download brings, where any is offered.
 *
 * Resolves `undefined` where there is nothing to ask — none offered, none on
 * RomM, or the answer could not be read, which downloads the game alone —
 * `null` where the user cancelled, and the ticked ids otherwise.
 */
export async function askExtraContent(
  romId: number,
  romName: string,
  ask: (romName: string, answer: ExtraContentAnswer) => Promise<number[] | null>,
): Promise<number[] | null | undefined> {
  let answer: ExtraContentAnswer | null;
  try {
    answer = asAnswer(await getExtraContent(romId));
  } catch (e) {
    detach(debugLog(`extra content: read of rom ${romId} before its download failed: ${e}`));
    return undefined;
  }
  if (!showsExtraContent(answer)) return undefined;
  return ask(romName, answer);
}
