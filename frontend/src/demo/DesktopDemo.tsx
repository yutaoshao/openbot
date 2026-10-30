import { Suspense, useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { useI18n } from "../i18n";
import { ChatWorkspace } from "../components/desktop/ChatWorkspace";
import { DesktopSidebar } from "../components/desktop/DesktopSidebar";
import { managementScreens } from "../components/desktop/management";
import { useDemoChat } from "./use-demo-chat";
import type { DemoScenario } from "./chat-types";
import "../components/desktop/desktop.css";

function DemoWorkspace(): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const chat = useDemoChat();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const management = location.pathname.includes("/manage/");
  const screen = managementScreens.find((item) => location.pathname.endsWith(`/manage/${item.key}`));

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
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n" && !chat.busy) {
        event.preventDefault(); chat.selectConversation(null); navigate("/desktop-demo");
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [chat, navigate]);

  return <div className="desktop-demo">
    <DesktopSidebar chat={chat} theme={theme} toggleTheme={() => setTheme((value) => value === "light" ? "dark" : "light")} />
    <main className="demo-main">
      <header className="demo-titlebar">
        <span>{screen ? t(screen.label) : chat.title}</span>
        <div className="demo-preview-controls">
          <span className="demo-preview-label">{t("desktop.synthetic")}</span>
          <select aria-label={t("desktop.scenario")} value={chat.scenario} disabled={chat.busy}
            onChange={(event) => { chat.chooseScenario(event.target.value as DemoScenario); navigate("/desktop-demo"); }}>
            {(["ready", "empty", "starting", "offline", "error", "long"] as const).map((state) =>
              <option key={state} value={state}>{t(`desktop.state.${state}`)}</option>)}
          </select>
        </div>
      </header>
      <Suspense fallback={<div className="demo-page-loading" role="status">{t("common.loading")}</div>}>
        <div className={management ? "demo-admin" : "demo-chat-slot"}>
          <Routes>
            <Route index element={<ChatWorkspace chat={chat} />} />
            {managementScreens.map(({ key, page: Page }) => <Route key={key} path={`manage/${key}`} element={<Page />} />)}
            <Route path="*" element={<ChatWorkspace chat={chat} />} />
          </Routes>
        </div>
      </Suspense>
    </main>
  </div>;
}

export default function DesktopDemo(): JSX.Element {
  const [client] = useState(() => new QueryClient({ defaultOptions: {
    queries: { retry: false, staleTime: 30_000, refetchOnWindowFocus: false },
  } }));
  return <QueryClientProvider client={client}><DemoWorkspace /></QueryClientProvider>;
}
