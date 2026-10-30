import { useI18n, type Language } from "../i18n";
import { DesktopSettings } from "./DesktopSettings";

export function DesktopPreferencesPage() {
  const { t, language, setLanguage } = useI18n();
  return <div className="settings-page">
    <section className="page-header"><div>
      <p className="page-eyebrow">{t("nav.settings")}</p>
      <h1 className="page-title">{t("settings.title")}</h1>
      <p className="page-subtitle">{t("desktopServices.pageHint")}</p>
    </div></section>
    <div className="settings-shell">
      <nav className="settings-nav surface-panel" aria-label={t("nav.settings")}>
        {[["general", "settings.general"], ["connection", "desktopLive.connectionSettings"], ["services", "desktopServices.title"],
          ["wechat-login", "desktop.wechatLogin"], ["execution", "desktopLive.execution"], ["data-import", "desktopImport.title"],
          ["app-updates", "desktopUpdate.title"], ...(window.__TAURI_INTERNALS__ ? [["desktop-integration", "desktopServices.appSettings"]] : [])].map(([id, key]) =>
          <a className="settings-nav-link" href={`#${id}`} key={id}>{t(key)}</a>)}
      </nav>
      <div className="settings-content">
        <section className="surface-panel settings-section" id="general">
          <h2>{t("settings.general")}</h2>
          <label className="desktop-service-field"><span className="field-label">{t("settings.language")}</span>
            <select className="select" value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
              <option value="zh-CN">简体中文</option><option value="en-US">English</option>
            </select>
            <span className="field-help">{t("settings.languageLocalHint")}</span>
          </label>
        </section>
        <DesktopSettings />
      </div>
    </div>
  </div>;
}
