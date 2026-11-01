import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Plus, Search, Settings } from "lucide-react";

import { useI18n } from "../../i18n";
import { api } from "../../lib/api";
import { desktopLinkPath, type DesktopBasePath } from "../../desktop/location";
import { Button } from "../ui/button";

import type { ChatViewModel } from "./chat-view";

export function DesktopSidebar({ chat, basePath = "/desktop-demo" }: {
  chat: ChatViewModel; basePath?: DesktopBasePath;
}): JSX.Element {
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [search, setSearch] = useState("");
  const viewingChat = location.pathname.replace(/\/$/, "") === basePath;
  const conversationPath = desktopLinkPath(basePath);
  const conversations = useQuery({ queryKey: ["conversations", "desktop-sidebar", search],
    queryFn: () => api.get<Array<{ id: string; title: string | null; platform: string }>>(`/api/conversations?limit=100${search ? `&q=${encodeURIComponent(search)}` : ""}`) });
  const visible = basePath === "/desktop" ? conversations.data ?? []
    : (conversations.data ?? []).filter((item) => (item.title ?? "").toLowerCase().includes(search.toLowerCase()));

  return <aside className="demo-sidebar" aria-label={t("desktop.sidebar")}>
    <div className="demo-sidebar-brand">OpenBot <span>Mac</span></div>
    <Button variant="outline" className="demo-new-chat" disabled={chat.busy} onClick={() => {
      chat.selectConversation(null); navigate(conversationPath);
    }}><Plus size={15} />{t("desktop.newChat")}<kbd>⌘ N</kbd></Button>
    <label className="demo-search"><Search size={14} />
      <input value={search} onChange={(event) => setSearch(event.target.value)}
        placeholder={t("desktop.search")} aria-label={t("desktop.search")} />
    </label>
    <p className="demo-sidebar-caption">{t("desktop.recent")}</p>
    <nav className="demo-history" aria-label={t("nav.conversations")}>
      {visible.map((item) => <button key={item.id} type="button" disabled={chat.busy}
        className={`demo-history-item${viewingChat && chat.selectedId === item.id ? " is-selected" : ""}`}
        aria-current={viewingChat && chat.selectedId === item.id ? "page" : undefined}
        onClick={() => { chat.selectConversation(item.id); navigate(conversationPath); }}>
        <span>{item.title || t("desktopLive.untitled")}</span>
      </button>)}
      {visible.length === 0 && <p className="demo-muted">{t("desktop.noMatches")}</p>}
    </nav>
    <div className="demo-sidebar-bottom">
      <Link className="desktop-preferences-entry" to={desktopLinkPath(basePath, "/settings/general")}>
        <Settings size={17} aria-hidden="true" />{t("desktop.settings.title")}
      </Link>
    </div>
  </aside>;
}
