import { useEffect, useState } from "react";
import { Check, Moon, Sun } from "lucide-react";
import { Link } from "react-router-dom";

import { useI18n, type Language } from "../i18n";
import { DesktopSetupForm, LoginStartup, WebConsole, useDesktopStatus } from "./DesktopSettings";
import { DesktopServices } from "./DesktopServices";
import { ExecutionPermissions } from "./ExecutionPermissions";
import { DesktopImport } from "./DesktopImport";
import { DesktopUpdates } from "./DesktopUpdates";
import { preferencePages, type PreferencePage } from "./settings-navigation";
import { desktopLinkPath, type DesktopBasePath } from "./location";

type Theme = "light" | "dark";

function GeneralPreferences({ theme, basePath }: { theme: Theme; basePath: DesktopBasePath }): JSX.Element {
  const { t, language, setLanguage } = useI18n();
  const status = useDesktopStatus();
  return <div className="desktop-preference-sections">
    <section><h2>{t("desktop.preferences.interface")}</h2><div className="desktop-preference-group">
      <div className="desktop-preference-row"><div><strong>{t("desktop.settings.language")}</strong><p>{t("settings.languageLocalHint")}</p></div>
        <select className="select" aria-label={t("desktop.settings.language")} value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
          <option value="zh-CN">简体中文</option><option value="en-US">English</option>
        </select>
      </div>
      <div className="desktop-preference-row"><div><strong>{t("desktop.settings.appearance")}</strong><p>{t("desktop.preferences.appearanceHint")}</p></div>
        <Link className="desktop-preference-value-link" to={desktopLinkPath(basePath, "/settings/appearance")}>{t(theme === "light" ? "desktop.settings.day" : "desktop.settings.night")}<span aria-hidden="true">›</span></Link>
      </div>
    </div></section>
    <section><h2>{t("desktop.preferences.runtime")}</h2><div className="desktop-preference-group">
      {status.isPending ? <p className="desktop-preference-status" role="status">{t("common.loading")}</p>
        : !status.data ? <p className="desktop-preference-status" role="alert">{t("desktopLive.statusError")}</p>
        : <>
          <div className="desktop-preference-row"><div><strong>{t("desktopLive.modelName")}</strong><p>{t("desktop.preferences.modelHint")}</p></div>
            <Link className="desktop-preference-value-link" to={desktopLinkPath(basePath, "/settings/connection")}>{status.data.model.model}<span aria-hidden="true">›</span></Link></div>
          <div className="desktop-preference-row"><div><strong>{t("desktopLive.workDir")}</strong><p>{t("desktopLive.workDirHint")}</p></div>
            <Link className="desktop-preference-value-link desktop-preference-path" to={desktopLinkPath(basePath, "/settings/connection")} title={status.data.work_dir}>{status.data.work_dir}<span aria-hidden="true">›</span></Link></div>
        </>}
    </div></section>
    {basePath === "/desktop" && window.__TAURI_INTERNALS__ && <section>
      <h2>{t("desktopServices.appSettings")}</h2><LoginStartup /><WebConsole />
    </section>}
  </div>;
}

function AppearancePreferences({ theme, onThemeChange }: { theme: Theme; onThemeChange: (value: Theme) => void }): JSX.Element {
  const { t } = useI18n();
  return <section className="desktop-preference-sections"><div>
    <h2>{t("desktop.preferences.theme")}</h2><p className="desktop-preference-intro">{t("desktop.preferences.appearanceHint")}</p>
    <fieldset className="desktop-theme-options" aria-label={t("desktop.preferences.theme")}>
      {([{ value: "light", key: "day", icon: Sun }, { value: "dark", key: "night", icon: Moon }] as const).map(({ value, key, icon: Icon }) =>
        <label className="desktop-theme-option" key={value}>
          <input type="radio" name="desktop-appearance" checked={theme === value} onChange={() => onThemeChange(value)} />
          <span className="desktop-theme-choice">
            <span className="desktop-theme-preview" data-theme-preview={value} aria-hidden="true"><i /><span><b /><b /><b /><em /></span></span>
            <span className="desktop-theme-caption"><Icon size={16} aria-hidden="true" />{t(`desktop.settings.${key}`)}<Check size={16} className="desktop-theme-check" aria-hidden="true" /></span>
          </span>
        </label>)}
    </fieldset>
  </div></section>;
}

function RuntimePreference({ page, active }: { page: Exclude<PreferencePage, "general" | "appearance">; active: boolean }): JSX.Element {
  const { t } = useI18n();
  const status = useDesktopStatus();
  if (status.isPending) return <p role="status">{t("common.loading")}</p>;
  if (!status.data) return <div role="alert"><p>{t("desktopLive.statusError")}</p><button className="btn secondary" onClick={() => void status.refetch()}>{t("desktop.reconnect")}</button></div>;
  switch (page) {
    case "connection": return <DesktopSetupForm status={status.data} />;
    case "services": return <DesktopServices busy={status.data.busy} active={active} />;
    case "execution": return <ExecutionPermissions permissions={status.data.permissions} />;
    case "data-import": return <DesktopImport busy={status.data.busy} available={!status.data.configured} result={status.data.import_result} />;
    case "updates": return <DesktopUpdates busy={status.data.busy} />;
  }
}

function PreferencePageContent({ page, theme, onThemeChange, basePath, active }: {
  page: PreferencePage; theme: Theme; onThemeChange: (value: Theme) => void; basePath: DesktopBasePath; active: boolean;
}): JSX.Element {
  const { t } = useI18n();
  const descriptor = preferencePages.find((item) => item.key === page)!;
  return <div className="desktop-preference-page">
    <header className="page-header"><h1 className="page-title">{t(descriptor.label)}</h1></header>
    {page === "general" ? <GeneralPreferences theme={theme} basePath={basePath} />
      : page === "appearance" ? <AppearancePreferences theme={theme} onThemeChange={onThemeChange} />
      : <div className="desktop-preference-runtime"><RuntimePreference page={page} active={active} /></div>}
  </div>;
}

/** Category navigation preserves the drafts previously kept by the single settings page. */
export function PreferencePanels({ activePage, theme, onThemeChange, basePath }: {
  activePage?: PreferencePage; theme: Theme; onThemeChange: (value: Theme) => void; basePath: DesktopBasePath;
}): JSX.Element {
  const [visited, setVisited] = useState<PreferencePage[]>([]);
  const panels = activePage && !visited.includes(activePage) ? [...visited, activePage] : visited;
  useEffect(() => {
    if (activePage) setVisited((pages) => pages.includes(activePage) ? pages : [...pages, activePage]);
  }, [activePage]);
  return <>{panels.map((page) => <div className="desktop-retained-preference" key={page} hidden={page !== activePage}>
    <PreferencePageContent page={page} theme={theme} onThemeChange={onThemeChange} basePath={basePath} active={page === activePage} />
  </div>)}</>;
}
