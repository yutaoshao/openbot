import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { ChatBar } from "./chat-bar";

const navItems = [
  ["/", "Dashboard"],
  ["/conversations", "Conversations"],
  ["/memory", "Memory"],
  ["/tools", "Tools"],
  ["/scheduler", "Scheduler"],
  ["/monitoring", "Monitoring"],
  ["/settings", "Settings"],
] as const;

export function Layout(): JSX.Element {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`app-shell${collapsed ? " sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">OpenBot</div>
        <button className="btn secondary" type="button" onClick={() => setCollapsed((prev) => !prev)} style={{ marginBottom: 10 }}>
          {collapsed ? "Expand" : "Collapse"}
        </button>
        {navItems.map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
            end={to === "/"}
          >
            {collapsed ? label.slice(0, 1) : label}
          </NavLink>
        ))}
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <h1 style={{ margin: 0 }}>Management Console</h1>
            <p style={{ margin: "4px 0 0", color: "var(--muted)" }}>
              Phase 4 dashboard and control plane
            </p>
          </div>
          <span className="status-chip">Agent Online</span>
        </header>
        <Outlet />
      </main>
      <ChatBar />
    </div>
  );
}
