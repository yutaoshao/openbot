import { createContext, useCallback, useContext, useEffect, useId, useMemo, useState, type ReactNode } from "react";

type DraftState = { dirty: boolean; pending: boolean };
type DraftRegistry = DraftState & { update: (id: string, state?: DraftState) => void };
const SettingsDrafts = createContext<DraftRegistry | null>(null);

export function SettingsDraftsProvider({ children }: { children: ReactNode }): JSX.Element {
  const [drafts, setDrafts] = useState<Record<string, DraftState>>({});
  const update = useCallback((id: string, state?: DraftState) => {
    setDrafts((current) => {
      if (current[id]?.dirty === state?.dirty && current[id]?.pending === state?.pending) return current;
      const next = { ...current };
      if (state) next[id] = state; else delete next[id];
      return next;
    });
  }, []);
  const value = useMemo(() => ({ update, dirty: Object.values(drafts).some((draft) => draft.dirty),
    pending: Object.values(drafts).some((draft) => draft.pending) }), [drafts, update]);
  return <SettingsDrafts.Provider value={value}>{children}</SettingsDrafts.Provider>;
}

export function useSettingsDrafts() { return useContext(SettingsDrafts); }

/** Form owners report only state; draft values and credentials stay with the form. */
export function useSettingsDraft(dirty: boolean, pending = false): void {
  const update = useSettingsDrafts()?.update;
  const id = useId();
  useEffect(() => { update?.(id, { dirty, pending }); }, [update, id, dirty, pending]);
  useEffect(() => () => update?.(id), [update, id]);
}
