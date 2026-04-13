import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useI18n } from "../i18n";
import { Icon, type IconName } from "./Icon";

type NavItem = {
  to: string;
  label: string;
  icon: IconName;
};

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

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("openbot_theme", theme);
  }, [theme]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-mark">
            <Icon name="spark" className="icon-sm" />
          </div>
          <div>
            <div className="sidebar-brand-title">OpenBot</div>
            <div className="sidebar-brand-subtitle">{t("layout.consoleLabel")}</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
              end={item.to === "/"}
            >
              <span className="nav-link-icon">
                <Icon name={item.icon} className="icon-sm" />
              </span>
              <span>{t(item.label)}</span>
            </NavLink>
          ))}
        </nav>

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
          <div className="topbar-search">
            <Icon name="search" className="icon-sm" />
            <input
              className="topbar-search-input"
              type="text"
              placeholder={t("layout.searchPlaceholder")}
            />
          </div>
          <div className="topbar-meta">
            <span className="topbar-pill">
              <span className="topbar-pill-dot" />
              {t("layout.agentOnline")}
            </span>
            <button className="icon-button" type="button" aria-label={t("layout.notifications")}>
              <Icon name="notifications" className="icon-sm" />
            </button>
            <button className="icon-button" type="button" aria-label={t("layout.help")}>
              <Icon name="help" className="icon-sm" />
            </button>
          </div>
        </header>

        <div className="workspace-scroll">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
