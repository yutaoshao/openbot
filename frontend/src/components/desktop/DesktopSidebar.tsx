import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, useNavigate } from "react-router-dom";
import { ChevronDown, Moon, Plus, Search, Settings2, Sun } from "lucide-react";

import { useI18n } from "../../i18n";
import { api } from "../../lib/api";
import { Button } from "../ui/button";
import { managementScreens } from "./management";

import type { ChatViewModel } from "./chat-view";

export function DesktopSidebar({ chat, theme, toggleTheme, basePath = "/desktop-demo", footer }: {
  chat: ChatViewModel; theme: "light" | "dark"; toggleTheme: () => void; basePath?: string; footer?: string;
}): JSX.Element {
  const { t, language, setLanguage } = useI18n();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [managementOpen, setManagementOpen] = useState(false);
  const conversations = useQuery({ queryKey: ["conversations", "desktop-sidebar", search],
    queryFn: () => api.get<Array<{ id: string; title: string | null; platform: string }>>(`/api/conversations?limit=100${search ? `&q=${encodeURIComponent(search)}` : ""}`) });
  const visible = basePath === "/desktop" ? conversations.data ?? []
    : (conversations.data ?? []).filter((item) => (item.title ?? "").toLowerCase().includes(search.toLowerCase()));

  return <aside className="demo-sidebar" aria-label={t("desktop.sidebar")}>
    <div className="demo-sidebar-brand">OpenBot <span>Mac</span></div>
    <Button variant="outline" className="demo-new-chat" disabled={chat.busy} onClick={() => {
      chat.selectConversation(null); navigate(basePath);
    }}><Plus size={15} />{t("desktop.newChat")}<kbd>⌘ N</kbd></Button>
    <label className="demo-search"><Search size={14} />
      <input value={search} onChange={(event) => setSearch(event.target.value)}
        placeholder={t("desktop.search")} aria-label={t("desktop.search")} />
    </label>
    <p className="demo-sidebar-caption">{t("desktop.recent")}</p>
    <nav className="demo-history" aria-label={t("nav.conversations")}>
      {visible.map((item) => <button key={item.id} type="button" disabled={chat.busy}
        className={`demo-history-item${chat.selectedId === item.id ? " is-selected" : ""}`}
        onClick={() => { chat.selectConversation(item.id); navigate(basePath); }}>
        <span>{item.title || t("desktopLive.untitled")}</span>
      </button>)}
      {visible.length === 0 && <p className="demo-muted">{t("desktop.noMatches")}</p>}
    </nav>
    <div className="demo-sidebar-bottom">
      {managementOpen && <nav className="demo-management-menu" aria-label={t("desktop.management")}>
        {managementScreens.map(({ key, label, icon: Icon }) => <NavLink key={key}
          to={`${basePath}/manage/${key}`} className={({ isActive }) => `demo-management-link${isActive ? " is-selected" : ""}`}>
          <Icon size={15} />{t(label)}
        </NavLink>)}
      </nav>}
      <button type="button" className="demo-management-toggle" aria-expanded={managementOpen}
        onClick={() => setManagementOpen((value) => !value)}>
        <Settings2 size={16} />{t("desktop.management")}<ChevronDown size={13} />
      </button>
      <div className="demo-sidebar-utilities">
        <button type="button" aria-label={t(theme === "light" ? "theme.dark" : "theme.light")}
          title={t(theme === "light" ? "theme.dark" : "theme.light")} onClick={toggleTheme}>
          {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
        </button>
        <button type="button" aria-label={t("desktop.language")} onClick={() => setLanguage(language === "zh-CN" ? "en-US" : "zh-CN")}>
          {language === "zh-CN" ? "EN" : "中文"}
        </button>
        <span>{footer ?? t("desktop.preview")}</span>
      </div>
    </div>
  </aside>;
}
