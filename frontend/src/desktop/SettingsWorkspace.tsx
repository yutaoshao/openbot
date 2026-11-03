import { Suspense, useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { useI18n } from "../i18n";
import { currentSettingsDestination, preferencePages, settingsGroups, settingsHelp, type SettingsDestination } from "./settings-navigation";
import { desktopLinkPath, type DesktopBasePath } from "./location";
import { PreferencePanels } from "./PreferencePages";
import { managementScreens } from "../components/desktop/management";
import "../components/desktop/settings-workspace.css";
import "../components/desktop/settings-content.css";

function SettingsNavigationLink({ destination, basePath }: { destination: SettingsDestination; basePath: DesktopBasePath }): JSX.Element {
  const { t } = useI18n();
  const Icon = destination.icon;
  return <NavLink to={desktopLinkPath(basePath, destination.path)} className={({ isActive }) => `desktop-preferences-nav-link${isActive ? " is-selected" : ""}`}>
    <Icon size={17} aria-hidden="true" /><span>{t(destination.label)}</span>
  </NavLink>;
}

export function SettingsWorkspace({ basePath, theme, onThemeChange, statusLabel }: {
  basePath: DesktopBasePath; theme: "light" | "dark"; onThemeChange: (theme: "light" | "dark") => void; statusLabel: string;
}): JSX.Element {
  const { t } = useI18n();
  const location = useLocation();
  const content = useRef<HTMLElement>(null);
  const [search, setSearch] = useState("");
  const [visitedManagement, setVisitedManagement] = useState<string[]>([]);
  const query = search.trim().toLocaleLowerCase();
  const groups = settingsGroups.map((group) => ({ ...group,
    items: group.items.filter((item) => `${t(group.label)} ${t(item.label)}`.toLocaleLowerCase().includes(query)),
  })).filter((group) => group.items.length > 0);
  const current = currentSettingsDestination(location.pathname, basePath);
  const retainedPage = current?.key === "memory" || current?.key === "scheduler" ? current.key : undefined;
  const managementPanels = retainedPage && !visitedManagement.includes(retainedPage) ? [...visitedManagement, retainedPage] : visitedManagement;
  useEffect(() => {
    if (retainedPage) setVisitedManagement((pages) => pages.includes(retainedPage) ? pages : [...pages, retainedPage]);
  }, [retainedPage]);
  const activePreference = preferencePages.find(({ key }) => key === current?.key)?.key;

  useEffect(() => { if (content.current) content.current.scrollTop = 0; }, [location.pathname]);

  return <div className="desktop-preferences-workspace">
    <div className="desktop-preferences-window">
      <aside className="desktop-preferences-sidebar" aria-label={t("desktop.preferences.navigation")}>
        <div className="desktop-preferences-sidebar-header">
          <label className="desktop-preferences-search"><Search size={16} aria-hidden="true" />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("desktop.preferences.search")}
              aria-label={t("desktop.preferences.search")} />
            {search && <button type="button" onClick={() => setSearch("")} aria-label={t("desktop.preferences.clearSearch")}><X size={14} aria-hidden="true" /></button>}
          </label>
        </div>
        <nav className="desktop-preferences-navigation" aria-label={t("desktop.preferences.tabs")}>
          {groups.map((group) => <section key={group.label} className="desktop-preferences-nav-group">
            <h2>{t(group.label)}</h2>
            {group.items.map((destination) => <SettingsNavigationLink key={destination.key} destination={destination} basePath={basePath} />)}
          </section>)}
          {groups.length === 0 && <p className="desktop-preferences-no-results" role="status">{t("desktop.preferences.noResults")}</p>}
        </nav>
        <div className="desktop-preferences-sidebar-footer"><SettingsNavigationLink destination={settingsHelp} basePath={basePath} /><span>OpenBot</span></div>
      </aside>
      <main ref={content} className="desktop-preferences-content" data-settings-page={current?.key ?? "general"} aria-label={current ? t(current.label) : t("desktop.settings.title")}>
        <div className="desktop-preferences-status">{statusLabel}</div>
        <div className="desktop-preferences-page-body">
          <PreferencePanels activePage={activePreference} theme={theme} onThemeChange={onThemeChange} basePath={basePath} />
          <Suspense fallback={<p role="status">{t("common.loading")}</p>}>
            {managementScreens.filter(({ key }) => managementPanels.includes(key)).map(({ key, page: Page }) =>
              <div key={key} hidden={key !== retainedPage}><Page /></div>)}
            <Routes>
              {preferencePages.map(({ key }) => <Route key={key} path={`settings/${key}`} element={null} />)}
              {managementScreens.filter(({ key }) => key !== "settings").map(({ key, page: Page }) =>
                <Route key={key} path={`manage/${key}`} element={key === "memory" || key === "scheduler" ? null : <Page />} />)}
              <Route path="manage/settings" element={<Navigate to={desktopLinkPath(basePath, "/settings/connection")} replace />} />
              <Route path="*" element={<Navigate to={desktopLinkPath(basePath, "/settings/general")} replace />} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  </div>;
}
