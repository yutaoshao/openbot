import { Download, FolderCog, Palette, Settings, ShieldCheck, SlidersHorizontal, Sparkles, type LucideIcon } from "lucide-react";

import { managementScreens } from "../components/desktop/management";
import type { DesktopBasePath } from "./location";

export type PreferencePage = "general" | "appearance" | "connection" | "services" | "execution" | "data-import" | "updates";
export type SettingsDestination = { key: string; label: string; path: string; icon: LucideIcon };

export const preferencePages: ReadonlyArray<SettingsDestination & { key: PreferencePage }> = [
  { key: "general", label: "settings.general", path: "/settings/general", icon: Settings },
  { key: "appearance", label: "desktop.settings.appearance", path: "/settings/appearance", icon: Palette },
  { key: "connection", label: "desktop.preferences.connection", path: "/settings/connection", icon: FolderCog },
  { key: "services", label: "desktop.preferences.services", path: "/settings/services", icon: SlidersHorizontal },
  { key: "execution", label: "desktopLive.execution", path: "/settings/execution", icon: ShieldCheck },
  { key: "data-import", label: "desktopImport.title", path: "/settings/data-import", icon: Download },
  { key: "updates", label: "desktopUpdate.title", path: "/settings/updates", icon: Sparkles },
];

const managementDestinations = managementScreens.filter((screen) => screen.key !== "settings").map(({ key, label, icon }) => ({
  key, label, icon, path: `/manage/${key}`,
}));

const allDestinations = [...preferencePages, ...managementDestinations];
const destinationsFor = (...keys: string[]) => keys.map((key) => allDestinations.find((destination) => destination.key === key)!);

export const settingsGroups = [
  { label: "desktop.preferences.personal", items: destinationsFor("general", "appearance") },
  { label: "desktop.preferences.agent", items: destinationsFor("connection", "services", "execution") },
  { label: "desktop.preferences.workspace", items: destinationsFor("conversations", "memory", "tools", "scheduler") },
  { label: "desktop.preferences.operations", items: destinationsFor("overview", "monitoring", "logs", "data-import", "updates") },
];

export const settingsHelp = managementDestinations.find((destination) => destination.key === "help")!;

export function currentSettingsDestination(pathname: string, basePath: DesktopBasePath): SettingsDestination | undefined {
  return allDestinations.find((destination) => `${basePath}${destination.path}` === pathname.replace(/\/$/, ""));
}
