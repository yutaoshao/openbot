import { useState, type ReactNode } from "react";
import { useI18n } from "../i18n";
import type { SecretDraft } from "./service-types";

export function TextField({ label, value, onChange, hint, type = "text", required = false }: {
  label: string; value: string | null; onChange: (value: string) => void;
  hint?: string; type?: "text" | "url"; required?: boolean;
}) {
  return <label className="desktop-service-field"><span className="field-label">{label}</span>
    <input className="input" type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)} autoComplete="off" required={required} />
    {hint && <span className="field-help">{hint}</span>}
  </label>;
}

export function NumberField({ label, value, onChange, min = 0, step = 1, nullable = false }: {
  label: string; value: number | null; onChange: (value: number | null) => void;
  min?: number; step?: number | "any"; nullable?: boolean;
}) {
  return <label className="desktop-service-field"><span className="field-label">{label}</span>
    <input className="input" type="number" value={value ?? ""} min={min} step={step} required={!nullable}
      onChange={(e) => onChange(e.target.value === "" && nullable ? null : e.target.valueAsNumber)} />
  </label>;
}

export function ChoiceField<T extends string>({ label, value, choices, onChange }: {
  label: string; value: T; choices: ReadonlyArray<readonly [T, string]>; onChange: (value: T) => void;
}) {
  return <label className="desktop-service-field"><span className="field-label">{label}</span>
    <select className="select" value={value} onChange={(e) => onChange(e.target.value as T)}>
      {choices.map(([key, text]) => <option value={key} key={key}>{text}</option>)}
    </select>
  </label>;
}

export function ServiceToggle({ label, checked, onChange }: {
  label: string; checked: boolean; onChange: (value: boolean) => void;
}) {
  return <label className="desktop-service-toggle"><span>{label}</span>
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
  </label>;
}

export function KeywordsField({ label, values, onChange }: { label: string; values: string[]; onChange: (values: string[]) => void }) {
  const { t } = useI18n();
  const [text, setText] = useState(values.join(", "));
  return <TextField label={label} value={text} hint={t("desktopServices.commaSeparated")} onChange={(next) => {
    setText(next); onChange(next.split(/[,，]/).map((s) => s.trim()).filter(Boolean));
  }} />;
}

export function ServiceGroup({ title, children, hint }: { title: string; children: ReactNode; hint?: string }) {
  return <fieldset className="desktop-service-group"><legend>{title}</legend>
    {hint && <p className="field-help">{hint}</p>}
    <div className="settings-grid">{children}</div>
  </fieldset>;
}

export function SecretField({ name, label, saved, draft, onChange }: {
  name: string; label: string; saved: boolean; draft: SecretDraft; onChange: (value: SecretDraft) => void;
}) {
  const { t } = useI18n();
  const cleared = draft.cleared.includes(name);
  return <div className="desktop-service-field">
    <label><span className="field-label">{label}</span>
      <input className="input" type="password" autoComplete="new-password" value={draft.values[name] ?? ""} disabled={cleared}
        placeholder={t(saved ? "desktopLive.keyPreserve" : "desktopLive.keyNeeded")}
        onChange={(e) => onChange({ ...draft, values: { ...draft.values, [name]: e.target.value } })} />
    </label>
    {saved && <label className="desktop-secret-clear"><input type="checkbox" checked={cleared}
      onChange={(e) => onChange({
        values: { ...draft.values, [name]: "" },
        cleared: e.target.checked ? [...draft.cleared, name] : draft.cleared.filter((key) => key !== name),
      })} />{t("desktopServices.clearSecret", { name: label })}</label>}
  </div>;
}
