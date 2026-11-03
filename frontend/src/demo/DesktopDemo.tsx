import { Suspense, useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";

import { useI18n } from "../i18n";
import { ChatWorkspace } from "../components/desktop/ChatWorkspace";
import { DesktopSidebar } from "../components/desktop/DesktopSidebar";
import { useDemoChat } from "./use-demo-chat";
import { SettingsModal } from "../desktop/SettingsModal";
import { demoLinkPath } from "./location";
import type { DemoScenario } from "./chat-types";
import "../components/desktop/desktop.css";


function DemoWorkspace(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const chat = useDemoChat();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const settingsMode = /\/desktop-demo\/(?:manage|settings)(?:\/|$)/.test(location.pathname);

  useEffect(() => {
    const root = document.documentElement;
    const previousTheme = root.getAttribute("data-theme");
    root.setAttribute("data-desktop-demo", "true");
    root.setAttribute("data-desktop", "true");
    return () => {
      root.removeAttribute("data-desktop-demo");
      root.removeAttribute("data-desktop");
      if (previousTheme) root.setAttribute("data-theme", previousTheme); else root.removeAttribute("data-theme");
    };
  }, []);

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (!settingsMode && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n" && !chat.busy) {
        event.preventDefault(); chat.selectConversation(null); navigate(demoLinkPath("/desktop-demo"));
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [chat, navigate, settingsMode]);

  return <div className="desktop-demo">
    <div style={{ display: "contents" }} aria-hidden={settingsMode || undefined}><DesktopSidebar chat={chat} /></div>
    <main className="demo-main" aria-hidden={settingsMode || undefined}>
      <header className="demo-titlebar">
        <span>{chat.title}</span>
        <div className="demo-preview-controls">
          <span className="demo-preview-label">{t("desktop.synthetic")}</span>
          <select aria-label={t("desktop.scenario")} value={chat.scenario} disabled={chat.busy}
            onChange={(event) => { chat.chooseScenario(event.target.value as DemoScenario); navigate(demoLinkPath("/desktop-demo")); }}>
            {(["ready", "empty", "starting", "offline", "error", "long"] as const).map((state) =>
              <option key={state} value={state}>{t(`desktop.state.${state}`)}</option>)}
          </select>
        </div>
      </header>
      <Suspense fallback={<div className="demo-page-loading" role="status">{t("common.loading")}</div>}>
        <div className="demo-chat-slot"><ChatWorkspace chat={chat} /></div>
      </Suspense>
    </main>
    {settingsMode && <SettingsModal basePath="/desktop-demo" theme={theme} onThemeChange={setTheme} statusLabel={t("desktop.synthetic")} />}
  </div>;
}

export default function DesktopDemo(): JSX.Element {
  const [client] = useState(() => new QueryClient({ defaultOptions: {
    queries: { retry: false, staleTime: 30_000, refetchOnWindowFocus: false },
  } }));
  return <QueryClientProvider client={client}><DemoWorkspace /></QueryClientProvider>;
}
