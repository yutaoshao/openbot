import { Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { ChatPage } from "./pages/chat";
import { ConversationsPage } from "./pages/conversations";
import { DashboardPage } from "./pages/dashboard";
import { MemoryPage } from "./pages/memory";
import { MonitoringPage } from "./pages/monitoring";
import { SchedulerPage } from "./pages/scheduler";
import { SettingsPage } from "./pages/settings";
import { ToolsPage } from "./pages/tools";

export default function App(): JSX.Element {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="conversations" element={<ConversationsPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="tools" element={<ToolsPage />} />
        <Route path="scheduler" element={<SchedulerPage />} />
        <Route path="monitoring" element={<MonitoringPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
