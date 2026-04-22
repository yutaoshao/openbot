import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useI18n } from "../i18n";
import { Icon, type IconName } from "../components/Icon";
import { TopbarQuickSearch } from "../components/TopbarQuickSearch";
import { preloadAllRoutes, preloadRoute } from "./route-loaders";

type NavItem = {
  to: string;
  label: string;
  icon: IconName;
};

type Translate = (key: string) => string;

const navItems: NavItem[] = [
  { to: "/", label: "nav.dashboard", icon: "dashboard" },
  { to: "/chat", label: "nav.chat", icon: "chat" },
  { to: "/conversations", label: "nav.conversations", icon: "conversations" },
  { to: "/memory", label: "nav.memory", icon: "memory" },
  { to: "/tools", label: "nav.tools", icon: "tools" },
  { to: "/scheduler", label: "nav.scheduler", icon: "scheduler" },
  { to: "/monitoring", label: "nav.monitoring", icon: "monitoring" },
  { to: "/logs", label: "nav.logs", icon: "logs" },
  { to: "/settings", label: "nav.settings", icon: "settings" },
];

function getInitialTheme(): "light" | "dark" {
  const stored = localStorage.getItem("openbot_theme");
  if (stored === "dark" || stored === "light") {
    return stored;
  }
  return "light";
}

export function Layout(): JSX.Element {
  const [theme, setTheme] = useState<"light" | "dark">(getInitialTheme);
  const { t } = useI18n();
  const location = useLocation();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("openbot_theme", theme);
  }, [theme]);

  useEffect(() => {
    const timer = window.setTimeout(() => preloadAllRoutes(), 250);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <SidebarBrand t={t} />
        <SidebarNavigation t={t} />

        <div className="sidebar-footer">
          <div className="sidebar-footnote">v0.1.0</div>
          <button
            className="theme-toggle"
            type="button"
            onClick={() => setTheme((current) => (current === "light" ? "dark" : "light"))}
          >
            {theme === "light" ? t("theme.dark") : t("theme.light")}
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <TopbarQuickSearch />
          <TopbarActions t={t} />
        </header>

        <div className="workspace-scroll">
          <Suspense fallback={<WorkspaceFallback title={t("common.loading")} />}>
            <div className="route-stage" key={location.pathname}>
              <Outlet />
            </div>
          </Suspense>
        </div>
      </main>
    </div>
  );
}

function SidebarBrand({ t }: { t: Translate }): JSX.Element {
  return (
    <div className="sidebar-brand">
      <div className="sidebar-brand-mark">
        <Icon name="spark" className="icon-sm" />
      </div>
      <div>
        <div className="sidebar-brand-title">OpenBot</div>
        <div className="sidebar-brand-subtitle">{t("layout.consoleLabel")}</div>
      </div>
    </div>
  );
}

function SidebarNavigation({ t }: { t: Translate }): JSX.Element {
  return (
    <nav className="sidebar-nav">
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          viewTransition
          className={({ isActive, isTransitioning }) =>
            `nav-link${isActive ? " active" : ""}${isTransitioning ? " transitioning" : ""}`
          }
          end={item.to === "/"}
          onMouseEnter={() => {
            void preloadRoute(item.to);
          }}
          onFocus={() => {
            void preloadRoute(item.to);
          }}
        >
          <span className="nav-link-icon">
            <Icon name={item.icon} className="icon-sm" />
          </span>
          <span>{t(item.label)}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function TopbarActions({ t }: { t: Translate }): JSX.Element {
  return (
    <div className="topbar-meta">
      <span className="topbar-pill">
        <span className="topbar-pill-dot" />
        {t("layout.agentOnline")}
      </span>
      <NavLink
        className={({ isTransitioning }) => `icon-button${isTransitioning ? " transitioning" : ""}`}
        to="/logs"
        viewTransition
        aria-label={t("layout.openLogs")}
        title={t("layout.openLogs")}
      >
        <Icon name="notifications" className="icon-sm" />
      </NavLink>
      <NavLink
        className={({ isTransitioning }) => `icon-button${isTransitioning ? " transitioning" : ""}`}
        to="/help"
        viewTransition
        aria-label={t("layout.openHelp")}
        title={t("layout.openHelp")}
      >
        <Icon name="help" className="icon-sm" />
      </NavLink>
    </div>
  );
}

function WorkspaceFallback({ title }: { title: string }): JSX.Element {
  return (
    <div className="workspace-fallback">
      <div className="surface-panel">
        <p className="surface-panel-label">{title}</p>
        <h2 className="surface-panel-title">Preparing workspace…</h2>
      </div>
    </div>
  );
}
