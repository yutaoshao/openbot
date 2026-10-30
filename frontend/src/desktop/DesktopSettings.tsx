import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { ExecutionPermissions } from "./ExecutionPermissions";
import { DesktopImport } from "./DesktopImport";
import { DesktopServices } from "./DesktopServices";
import { DesktopUpdates } from "./DesktopUpdates";
import { isDesktopDemoPath } from "../demo/location";
import { desktopInvoke } from "./native";
import type { DesktopStatus } from "./types";

export function useDesktopStatus(enabled = true) {
  return useQuery({ queryKey: ["desktop-status"], queryFn: () => api.get<DesktopStatus>("/api/desktop/status"), enabled, refetchInterval: 2000, retry: false });
}

function LoginStartup(): JSX.Element {
  const { t } = useI18n();
  const cache = useQueryClient();
  const status = useQuery({ queryKey: ["desktop-autostart"], queryFn: () => desktopInvoke<boolean>("desktop_autostart"), retry: false });
  const update = useMutation({
    mutationFn: (enabled: boolean) => desktopInvoke<boolean>("desktop_set_autostart", { enabled }),
    onSuccess: (enabled) => cache.setQueryData(["desktop-autostart"], enabled),
  });
  return <section className="surface-panel settings-section" id="desktop-integration">
    <label className="toggle-card"><div><span className="field-label">{t("desktopLive.loginStartup")}</span>
      <p className="field-help">{t("desktopLive.loginStartupHint")}</p></div>
      <input type="checkbox" checked={status.data ?? false} disabled={status.isPending || status.isError || update.isPending}
        onChange={(event) => update.mutate(event.target.checked)} /></label>
    {(status.isError || update.isError) && <p role="alert">{t("desktopLive.loginStartupError")}</p>}
  </section>;
}

function WebConsole(): JSX.Element {
  const { t } = useI18n();
  const open = useMutation({ mutationFn: () => desktopInvoke("desktop_open_web") });
  return <section className="surface-panel settings-section">
    <button className="btn secondary" type="button" disabled={open.isPending} onClick={() => open.mutate()}>{t("desktopLive.openWeb")}</button>
    {open.error && <p role="alert">{t("desktopLive.openWebError")}</p>}
  </section>;
}

export function DesktopSetupForm({ status, onboarding = false }: { status: DesktopStatus; onboarding?: boolean }): JSX.Element {
  const { t } = useI18n();
  const [provider, setProvider] = useState(status.model.provider);
  const [baseUrl, setBaseUrl] = useState(status.model.base_url);
  const [model, setModel] = useState(status.model.model);
  const [apiKey, setApiKey] = useState("");
  const [workDir, setWorkDir] = useState(status.work_dir);
  const [restartPending, setRestartPending] = useState(false);
  const picker = useMutation({
    mutationFn: () => desktopInvoke<string | null>("desktop_choose_directory"),
    onSuccess: (path) => { if (path) setWorkDir(path); },
  });
  const save = useMutation({
    mutationFn: () => api.post<{ requires_restart: boolean }>("/api/desktop/setup", {
      model: { provider, base_url: baseUrl.trim(), model: model.trim(), ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) },
      work_dir: workDir.trim(),
    }),
    onSuccess: (response) => { setApiKey(""); setRestartPending(response.requires_restart); },
  });
  return <section className="surface-panel settings-section desktop-setup" id="connection">
    <h2>{t(onboarding ? "desktopLive.setupTitle" : "desktopLive.connectionSettings")}</h2>
    <p className="field-help">{t("desktopLive.setupHint")}</p>
    <form onSubmit={(event) => { event.preventDefault(); if (!save.isPending && !restartPending) save.mutate(); }}>
      <div className="settings-grid">
        <label className="field-card"><span className="field-label">{t("desktopLive.provider")}</span>
          <select className="select" value={provider} onChange={(event) => setProvider(event.target.value as DesktopStatus["model"]["provider"])}>
            <option value="openai_compatible">OpenAI {t("desktopLive.compatible")}</option>
            <option value="openai_responses">OpenAI Responses</option>
            <option value="anthropic">Anthropic</option>
          </select></label>
        <label className="field-card"><span className="field-label">{t("desktopLive.modelName")}</span>
          <input className="input" value={model} onChange={(event) => setModel(event.target.value)} required autoComplete="off" /></label>
        <label className="field-card"><span className="field-label">{t("desktopLive.baseUrl")}</span>
          <input className="input" type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required autoComplete="off" /></label>
        <label className="field-card"><span className="field-label">API Key</span>
          <input className="input" type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password"
            placeholder={t(status.model.api_key_set ? "desktopLive.keyPreserve" : "desktopLive.keyNeeded")} />
          <p className="field-help">{t("desktopLive.keyHint")}</p></label>
        <label className="field-card desktop-wide-field"><span className="field-label">{t("desktopLive.workDir")}</span>
          <div className="desktop-directory-field"><input className="input" value={workDir} onChange={(event) => setWorkDir(event.target.value)} required autoComplete="off" />
            <button className="btn secondary" type="button" disabled={picker.isPending || !window.__TAURI_INTERNALS__} onClick={() => picker.mutate()}>{t("desktopLive.chooseDirectory")}</button></div>
          <p className="field-help">{t("desktopLive.workDirHint")}</p></label>
      </div>
      <p className="field-help desktop-data-path">{t("desktopLive.dataDir")}: <span className="mono">{status.data_dir}</span></p>
      {save.error && <p role="alert">{save.error.message}</p>}
      {picker.error && <p role="alert">{t("desktopLive.directoryError")}</p>}
      {restartPending && <p role="status">{t("desktopLive.restarting")}</p>}
      {status.busy && <p role="status">{t("desktopLive.busySettings")}</p>}
      <button className="btn" type="submit" disabled={status.busy || save.isPending || restartPending}>
        {t(save.isPending ? "common.loading" : "desktopLive.saveRestart")}
      </button>
    </form>
  </section>;
}

export function DesktopSettings(): JSX.Element {
  const { t } = useI18n();
  const status = useDesktopStatus();
  if (status.isPending) return <p role="status">{t("common.loading")}</p>;
  if (!status.data) return <p role="alert">{t("desktopLive.statusError")}</p>;
  return <div className="desktop-settings-stack">
    <DesktopSetupForm status={status.data} />
    <DesktopServices busy={status.data.busy} />
    <div id="execution"><ExecutionPermissions permissions={status.data.permissions} /></div>
    <DesktopImport busy={status.data.busy} available={!status.data.configured} result={status.data.import_result} />
    <DesktopUpdates busy={status.data.busy} />
    {window.__TAURI_INTERNALS__ && <><LoginStartup /><WebConsole /></>}
    {isDesktopDemoPath(window.location.pathname) && <p className="field-help">{t("desktopServices.nativePreviewHint")}</p>}
  </div>;
}
