import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";

const ChatPage = lazy(async () => ({ default: (await import("./pages/chat")).ChatPage }));
const ConversationsPage = lazy(async () => ({ default: (await import("./pages/conversations")).ConversationsPage }));
const DashboardPage = lazy(async () => ({ default: (await import("./pages/dashboard")).DashboardPage }));
const LogsPage = lazy(async () => ({ default: (await import("./pages/logs")).LogsPage }));
const MemoryPage = lazy(async () => ({ default: (await import("./pages/memory")).MemoryPage }));
const MonitoringPage = lazy(async () => ({ default: (await import("./pages/monitoring")).MonitoringPage }));
const SchedulerPage = lazy(async () => ({ default: (await import("./pages/scheduler")).SchedulerPage }));
const SettingsPage = lazy(async () => ({ default: (await import("./pages/settings")).SettingsPage }));
const ToolsPage = lazy(async () => ({ default: (await import("./pages/tools")).ToolsPage }));

export default function App(): JSX.Element {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="conversations" element={<ConversationsPage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="tools" element={<ToolsPage />} />
          <Route path="scheduler" element={<SchedulerPage />} />
          <Route path="monitoring" element={<MonitoringPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function RouteFallback(): JSX.Element {
  return (
    <div className="workspace-fallback">
      <div className="surface-panel">
        <p className="surface-panel-label">Loading</p>
        <h2 className="surface-panel-title">Preparing workspace…</h2>
      </div>
    </div>
  );
}
