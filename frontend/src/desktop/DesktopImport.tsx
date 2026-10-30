import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { isDesktopDemoPath } from "../demo/location";
import { desktopInvoke } from "./native";

type ImportPreview = {
  preview_id: string; source_dir: string; files: Array<{ path: string; bytes: number }>;
  schema_version: number; warnings: string[]; expires_at: number;
};

export function DesktopImport({ busy = false, available = true, result }: {
  busy?: boolean; available?: boolean; result?: { status: "imported" | "failed_restored" | "unknown" } | null;
}) {
  const { t, formatNumber, formatDateTime } = useI18n();
  const [source, setSource] = useState("");
  const sourceRef = useRef(source);
  const [stopped, setStopped] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [restarting, setRestarting] = useState(false);
  const previewRequest = useMutation({
    mutationFn: (source_dir: string) => api.post<ImportPreview>("/api/desktop/import/preview", { source_dir, acknowledgement: "source-stopped" }),
    onSuccess: (result, requested) => {
      if (sourceRef.current.trim() === requested) { setPreview(result); setAccepted(false); }
    },
  });
  const confirm = useMutation({
    mutationFn: () => api.post<{ requires_restart: boolean }>("/api/desktop/import/confirm", { preview_id: preview!.preview_id, acknowledgement: "copy-and-pause" }),
    onSuccess: (result) => setRestarting(result.requires_restart),
  });
  const updateSource = (next: string) => {
    sourceRef.current = next; setSource(next); setPreview(null); setAccepted(false);
    previewRequest.reset(); confirm.reset();
  };
  const picker = useMutation({
    mutationFn: () => isDesktopDemoPath(window.location.pathname) ? Promise.resolve("/demo/old-openbot") : desktopInvoke<string | null>("desktop_choose_directory"),
    onSuccess: (selected) => { if (selected) updateSource(selected); },
  });
  const pending = previewRequest.isPending || confirm.isPending || confirm.isSuccess || restarting;
  return <section className="surface-panel settings-section" id="data-import">
    <h2>{t("desktopImport.title")}</h2>
    <p className="field-help">{t("desktopImport.hint")}</p>
    {result && <p role="status">{t(`desktopImport.result.${result.status}`)}</p>}
    {!available && <p className="field-help">{t("desktopImport.alreadyConfigured")}</p>}
    {available && <fieldset disabled={pending} className="desktop-import-fields">
      <label className="desktop-service-field"><span className="field-label">{t("desktopImport.source")}</span>
        <div className="desktop-directory-field">
          <input className="input" value={source} onChange={(event) => updateSource(event.target.value)} autoComplete="off" />
          <button className="btn secondary" type="button" disabled={picker.isPending || (!window.__TAURI_INTERNALS__ && !isDesktopDemoPath(window.location.pathname))}
            onClick={() => picker.mutate()}>{t("desktopLive.chooseDirectory")}</button>
        </div>
      </label>
      <label className="desktop-import-ack"><input type="checkbox" checked={stopped} onChange={(event) => { setStopped(event.target.checked); setPreview(null); setAccepted(false); }} />{t("desktopImport.sourceStopped")}</label>
      <button className="btn secondary" type="button" disabled={!source.trim() || !stopped || busy}
        onClick={() => { setPreview(null); setAccepted(false); confirm.reset(); previewRequest.mutate(source.trim()); }}>{t("desktopImport.preview")}</button>
      {preview && <div className="desktop-import-preview">
        <p>{t("desktopImport.summary", { count: preview.files.length, size: formatNumber(preview.files.reduce((total, file) => total + file.bytes, 0) / 1024, { maximumFractionDigits: 1 }) })}</p>
        <p className="field-help">{t("desktopImport.expires", { time: formatDateTime(preview.expires_at * 1000) })}</p>
        <ul className="desktop-import-warnings">{preview.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        <details><summary>{t("desktopImport.fileList")}</summary><ul className="desktop-import-files">
          {preview.files.map((file) => <li key={file.path}><span>{file.path}</span><span>{formatNumber(file.bytes)} B</span></li>)}
        </ul></details>
        <label className="desktop-import-ack"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} />{t("desktopImport.accept")}</label>
        <button className="btn" type="button" disabled={!accepted || !stopped || busy || Date.now() >= preview.expires_at * 1000}
          onClick={() => confirm.mutate()}>{t("desktopImport.confirm")}</button>
      </div>}
    </fieldset>}
    {busy && <p role="status">{t("desktopLive.busySettings")}</p>}
    {previewRequest.isPending && <p role="status">{t("desktopImport.preparing")}</p>}
    {confirm.isPending && <p role="status">{t("desktopImport.copying")}</p>}
    {restarting && <p role="status">{t("desktopImport.restarting")}</p>}
    {confirm.isSuccess && !restarting && <p role="status">{t("desktopImport.demoCopied")}</p>}
    {(picker.error || previewRequest.error || confirm.error) && <p role="alert">{(picker.error || previewRequest.error || confirm.error)?.message}</p>}
  </section>;
}
