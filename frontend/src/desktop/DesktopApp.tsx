import { Suspense, useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { LoaderCircle } from "lucide-react";

import { ChatWorkspace } from "../components/desktop/ChatWorkspace";
import { DesktopSidebar } from "../components/desktop/DesktopSidebar";
import { managementScreens } from "../components/desktop/management";
import { useI18n } from "../i18n";
import { DesktopSetupForm, useDesktopStatus } from "./DesktopSettings";
import { DesktopImport } from "./DesktopImport";
import { desktopInvoke, readDesktopConnection } from "./native";
import { useDesktopChat } from "./use-desktop-chat";
import "../components/desktop/desktop.css";

function createClient(): QueryClient {
  return new QueryClient({ defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false, networkMode: "always" },
    mutations: { networkMode: "always" },
  } });
}

function useDesktopTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(() => localStorage.getItem("openbot_desktop_theme_v1") === "dark" ? "dark" : "light");
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.getAttribute("data-theme");
    root.setAttribute("data-desktop", "true");
    return () => {
      root.removeAttribute("data-desktop");
      if (previous) root.setAttribute("data-theme", previous); else root.removeAttribute("data-theme");
    };
  }, []);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("openbot_desktop_theme_v1", theme);
  }, [theme]);
  return { theme, toggleTheme: () => setTheme((value) => value === "light" ? "dark" : "light") };
}

function ConnectionScreen({ starting, detail, retry }: { starting?: boolean; detail?: string; retry?: () => void }): JSX.Element {
  const { t } = useI18n();
  return <main className="desktop-connection-screen"><div className="demo-service-message" role="status">
    {starting && <LoaderCircle className="demo-spinner" size={22} />}
    <h1>OpenBot</h1><h2>{t(starting ? "desktop.state.starting" : "desktop.state.error")}</h2>
    <p>{detail ? t(detail) : t("desktop.detail.starting")}</p>
    {retry && <button className="btn secondary" type="button" onClick={retry}>{t("desktop.reconnect")}</button>}
  </div></main>;
}

type SessionProps = { theme: "light" | "dark"; toggleTheme: () => void; instanceId: string };

function ReadyWorkspace({ theme, toggleTheme, instanceId }: SessionProps): JSX.Element {
  const { t } = useI18n();
  const chat = useDesktopChat(instanceId);
  const navigate = useNavigate();
  const location = useLocation();
  const management = location.pathname.includes("/manage/");
  const screen = managementScreens.find((item) => location.pathname.endsWith(`/manage/${item.key}`));
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n" && !chat.busy) {
        event.preventDefault(); chat.selectConversation(null); navigate("/desktop");
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [chat, navigate]);
  return <div className="desktop-demo">
    <DesktopSidebar chat={chat} theme={theme} toggleTheme={toggleTheme} basePath="/desktop" footer={t("desktopLive.localService")} />
    <main className="demo-main">
      <header className="demo-titlebar"><span>{screen ? t(screen.label) : chat.title}</span>
        <span className="demo-preview-label">{t("desktopLive.connected")}</span></header>
      <Suspense fallback={<p role="status">{t("common.loading")}</p>}>
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

function SessionContent({ theme, toggleTheme, instanceId }: SessionProps): JSX.Element {
  const { t, language, setLanguage } = useI18n();
  const status = useDesktopStatus();
  if (status.isPending) return <ConnectionScreen starting detail="common.loading" />;
  if (!status.data) return <ConnectionScreen detail="desktopLive.statusError" retry={() => void status.refetch()} />;
  if (!status.data.configured) return <main className="desktop-onboarding">
    <header><h1>OpenBot</h1><button className="btn ghost" type="button" onClick={() => setLanguage(language === "zh-CN" ? "en-US" : "zh-CN")}>{t("desktop.language")}</button></header>
    <DesktopSetupForm status={status.data} onboarding />
    <DesktopImport busy={status.data.busy} result={status.data.import_result} />
  </main>;
  return <ReadyWorkspace theme={theme} toggleTheme={toggleTheme} instanceId={instanceId} />;
}

function DesktopSession(props: SessionProps): JSX.Element {
  const [client] = useState(createClient);
  useEffect(() => () => { client.clear(); }, [client]);
  return <QueryClientProvider client={client}><SessionContent {...props} /></QueryClientProvider>;
}

function NativeConnection(): JSX.Element {
  const theme = useDesktopTheme();
  const cache = useQueryClient();
  const [retryError, setRetryError] = useState<string | undefined>();
  const connection = useQuery({ queryKey: ["desktop-native"], queryFn: readDesktopConnection, refetchInterval: 1000, refetchIntervalInBackground: true, retry: false });
  if (connection.data?.status === "ready" && !connection.isError) {
    return <DesktopSession key={connection.data.instanceId} instanceId={connection.data.instanceId!} {...theme} />;
  }
  const starting = connection.isPending || connection.data?.status === "starting";
  const detail = retryError || (connection.error instanceof Error ? connection.error.message : connection.data?.error);
  return <ConnectionScreen starting={starting} detail={detail} retry={starting ? undefined : () => {
    setRetryError(undefined);
    void desktopInvoke("desktop_retry").then(() => cache.invalidateQueries({ queryKey: ["desktop-native"] }))
      .catch((error: unknown) => setRetryError(error instanceof Error ? error.message : "desktopLive.serviceUnavailable"));
  }} />;
}

export default function DesktopApp(): JSX.Element {
  const [client] = useState(createClient);
  return <QueryClientProvider client={client}><NativeConnection /></QueryClientProvider>;
}
