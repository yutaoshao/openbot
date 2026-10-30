import { type ComponentType, type LazyExoticComponent } from "react";
import { BookOpen, CalendarDays, CircleHelp, FileText, Gauge, HeartPulse, MessageSquareText, Settings, Wrench,
  type LucideIcon } from "lucide-react";

import { ConversationsPage, DashboardPage, HelpPage, LogsPage, MemoryPage, MonitoringPage,
  SchedulerPage, SettingsPage, ToolsPage } from "../../app/route-loaders";

type ManagementScreen = { key: string; label: string; icon: LucideIcon;
  page: LazyExoticComponent<ComponentType> };

export const managementScreens: ManagementScreen[] = [
  { key: "overview", label: "nav.dashboard", icon: Gauge, page: DashboardPage },
  { key: "conversations", label: "nav.conversations", icon: MessageSquareText, page: ConversationsPage },
  { key: "memory", label: "nav.memory", icon: BookOpen, page: MemoryPage },
  { key: "tools", label: "nav.tools", icon: Wrench, page: ToolsPage },
  { key: "scheduler", label: "nav.scheduler", icon: CalendarDays, page: SchedulerPage },
  { key: "monitoring", label: "nav.monitoring", icon: HeartPulse, page: MonitoringPage },
  { key: "logs", label: "nav.logs", icon: FileText, page: LogsPage },
  { key: "settings", label: "nav.settings", icon: Settings, page: SettingsPage },
  { key: "help", label: "nav.help", icon: CircleHelp, page: HelpPage },
];
