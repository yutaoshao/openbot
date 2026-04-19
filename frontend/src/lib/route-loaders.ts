import { lazy } from "react";

const loadChatPage = async () => ({ default: (await import("../pages/chat")).ChatPage });
const loadConversationsPage = async () => ({ default: (await import("../pages/conversations")).ConversationsPage });
const loadDashboardPage = async () => ({ default: (await import("../pages/dashboard")).DashboardPage });
const loadHelpPage = async () => ({ default: (await import("../pages/help")).HelpPage });
const loadLogsPage = async () => ({ default: (await import("../pages/logs")).LogsPage });
const loadMemoryPage = async () => ({ default: (await import("../pages/memory")).MemoryPage });
const loadMonitoringPage = async () => ({ default: (await import("../pages/monitoring")).MonitoringPage });
const loadSchedulerPage = async () => ({ default: (await import("../pages/scheduler")).SchedulerPage });
const loadSettingsPage = async () => ({ default: (await import("../pages/settings")).SettingsPage });
const loadToolsPage = async () => ({ default: (await import("../pages/tools")).ToolsPage });

const ROUTE_LOADERS = {
  "/": loadDashboardPage,
  "/chat": loadChatPage,
  "/conversations": loadConversationsPage,
  "/memory": loadMemoryPage,
  "/tools": loadToolsPage,
  "/scheduler": loadSchedulerPage,
  "/monitoring": loadMonitoringPage,
  "/logs": loadLogsPage,
  "/help": loadHelpPage,
  "/settings": loadSettingsPage,
} as const;

const BACKGROUND_PRELOAD_PATHS = Object.keys(ROUTE_LOADERS) as Array<keyof typeof ROUTE_LOADERS>;

export const ChatPage = lazy(loadChatPage);
export const ConversationsPage = lazy(loadConversationsPage);
export const DashboardPage = lazy(loadDashboardPage);
export const HelpPage = lazy(loadHelpPage);
export const LogsPage = lazy(loadLogsPage);
export const MemoryPage = lazy(loadMemoryPage);
export const MonitoringPage = lazy(loadMonitoringPage);
export const SchedulerPage = lazy(loadSchedulerPage);
export const SettingsPage = lazy(loadSettingsPage);
export const ToolsPage = lazy(loadToolsPage);

export function preloadRoute(path: string): Promise<unknown> {
  const loader = ROUTE_LOADERS[path as keyof typeof ROUTE_LOADERS];
  return loader ? loader() : Promise.resolve();
}

export function preloadAllRoutes(): void {
  for (const path of BACKGROUND_PRELOAD_PATHS) {
    void preloadRoute(path);
  }
}
