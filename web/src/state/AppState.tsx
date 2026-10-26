import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { Health, Participant } from "../api/types";
import { useApi } from "../hooks/useApi";
import { isIsoDate, todayUTC } from "../format";

const KEY_PID = "runrank.participant";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode, quota): state still works in memory */
  }
}

export interface AppStateValue {
  participants: Participant[] | null;
  participantsLoading: boolean;
  participantsError: ApiError | null;
  reloadParticipants: () => void;
  participantId: number | null;
  participant: Participant | null;
  setParticipantId: (id: number) => void;
  asOf: string;
  setAsOf: (d: string) => void;
  /** Default "as of": today (UTC), or in demo mode the latest stored activity date (from /api/health). */
  referenceDate: string;
  health: Health | null;
}

const Ctx = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const parts = useApi((s) => api.participants(s), []);
  const health = useApi((s) => api.health(s), []);

  const [requestedId, setRequestedId] = useState<number | null>(() => {
    const raw = readStorage(KEY_PID);
    const n = raw === null ? NaN : Number(raw);
    return Number.isInteger(n) ? n : null;
  });
  // Not persisted: the personal and demo databases share this origin, and the right default differs.
  const [asOfChosen, setAsOfChosen] = useState<string | null>(null);
  const referenceDate = health.data?.reference_date ?? todayUTC();
  const asOf = asOfChosen ?? referenceDate;

  // Validate the requested id against the participant list; fall back to the first.
  const participant = useMemo(() => {
    const list = parts.data;
    if (!list || list.length === 0) return null;
    return list.find((p) => p.id === requestedId) ?? list[0];
  }, [parts.data, requestedId]);
  const participantId = participant ? participant.id : null;

  useEffect(() => {
    if (parts.data) writeStorage(KEY_PID, participantId === null ? null : String(participantId));
  }, [parts.data, participantId]);

  const setParticipantId = useCallback((id: number) => {
    setRequestedId(id);
    writeStorage(KEY_PID, String(id));
  }, []);
  const setAsOf = useCallback((d: string) => {
    if (isIsoDate(d)) setAsOfChosen(d);
  }, []);

  const value: AppStateValue = {
    participants: parts.data,
    participantsLoading: parts.loading,
    participantsError: parts.error,
    reloadParticipants: parts.reload,
    participantId,
    participant,
    setParticipantId,
    asOf,
    setAsOf,
    referenceDate,
    health: health.data,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppStateValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState must be used inside <AppStateProvider>");
  return v;
}
