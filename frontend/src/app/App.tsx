import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { Layout } from "./Layout";
import { BrowserSessionGate } from "../desktop/BrowserSessionGate";
import {
  ChatPage,
  ConversationsPage,
  DashboardPage,
  HelpPage,
  LogsPage,
  MemoryPage,
  MonitoringPage,
  SchedulerPage,
  SettingsPage,
  ToolsPage,
} from "./route-loaders";

const DesktopDemo = lazy(() => import("../demo/DesktopDemo"));
const DesktopApp = lazy(() => import("../desktop/DesktopApp"));

export default function App(): JSX.Element {
  return (
    <BrowserSessionGate><Routes>
      <Route path="/desktop/*" element={
        <Suspense fallback={<div role="status">OpenBot…</div>}><DesktopApp /></Suspense>
      } />
      <Route path="/desktop-demo/*" element={
        <Suspense fallback={<div role="status">OpenBot…</div>}><DesktopDemo /></Suspense>
      } />
      <Route path="/" element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="conversations" element={<ConversationsPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="scheduler" element={<SchedulerPage />} />
        <Route path="monitoring" element={<MonitoringPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="help" element={<HelpPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes></BrowserSessionGate>
  );
}
