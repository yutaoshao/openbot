import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useI18n } from "../i18n";

const navItems = [
  ["/", "nav.dashboard"],
  ["/chat", "nav.chat"],
  ["/conversations", "nav.conversations"],
  ["/memory", "nav.memory"],
  ["/tools", "nav.tools"],
  ["/scheduler", "nav.scheduler"],
  ["/monitoring", "nav.monitoring"],
  ["/logs", "nav.logs"],
  ["/settings", "nav.settings"],
] as const;

function getInitialTheme(): "light" | "dark" {
  const stored = localStorage.getItem("openbot_theme");
  if (stored === "dark" || stored === "light") return stored;
  return "light";
}

export function Layout(): JSX.Element {
  const [theme, setTheme] = useState<"light" | "dark">(getInitialTheme);
  const { t } = useI18n();
  const location = useLocation();
  const isChatPage = location.pathname === "/chat";

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("openbot_theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "light" ? "dark" : "light"));
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">OpenBot</div>
        <nav>
          {navItems.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
              end={to === "/"}
            >
              {t(label)}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="sidebar-version">v0.1.0</span>
          <button className="theme-toggle" type="button" onClick={toggleTheme}>
            {theme === "light" ? t("theme.dark") : t("theme.light")}
          </button>
        </div>
      </aside>
      {isChatPage ? (
        <main className="main-full">
          <Outlet />
        </main>
      ) : (
        <main className="main">
          <header className="topbar">
            <div>
              <h1>{t("layout.consoleTitle")}</h1>
            </div>
            <div className="status-indicator">
              <span className="status-dot" />
              {t("layout.agentOnline")}
            </div>
          </header>
          <Outlet />
        </main>
      )}
    </div>
  );
}
