import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useI18n } from "../i18n";
import { preloadRoute } from "../lib/route-loaders";
import { Icon } from "./Icon";

type SearchItem = {
  id: string;
  keywords: string[];
  label: string;
  meta: string;
  to: string;
};

function buildSearchItems(t: (key: string) => string): SearchItem[] {
  return [
    { id: "dashboard", label: t("nav.dashboard"), meta: "/dashboard", to: "/", keywords: ["dashboard", "overview", "health", "status", "概览", "状态"] },
    { id: "chat", label: t("nav.chat"), meta: "/chat", to: "/chat", keywords: ["chat", "assistant", "message", "聊天", "消息"] },
    { id: "conversations", label: t("nav.conversations"), meta: "/conversations", to: "/conversations", keywords: ["conversations", "history", "replay", "会话", "历史"] },
    { id: "memory", label: t("nav.memory"), meta: "/memory", to: "/memory", keywords: ["memory", "knowledge", "facts", "记忆", "知识"] },
    { id: "tools", label: t("nav.tools"), meta: "/tools", to: "/tools", keywords: ["tools", "tooling", "registry", "工具"] },
    { id: "scheduler", label: t("nav.scheduler"), meta: "/scheduler", to: "/scheduler", keywords: ["scheduler", "cron", "automation", "定时", "调度"] },
    { id: "monitoring", label: t("nav.monitoring"), meta: "/monitoring", to: "/monitoring", keywords: ["monitoring", "latency", "tokens", "telemetry", "监控", "延迟"] },
    { id: "logs", label: t("nav.logs"), meta: "/logs", to: "/logs", keywords: ["logs", "trace", "errors", "warnings", "日志", "错误"] },
    { id: "help", label: t("layout.help"), meta: "/help", to: "/help", keywords: ["help", "guide", "docs", "support", "帮助", "说明"] },
    { id: "settings", label: t("nav.settings"), meta: "/settings", to: "/settings", keywords: ["settings", "config", "telegram", "feishu", "设置", "配置"] },
  ];
}

function matches(item: SearchItem, query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  return [item.label, item.meta, ...item.keywords].some((value) =>
    value.toLowerCase().includes(normalized),
  );
}

export function TopbarQuickSearch(): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const blurTimerRef = useRef<number | null>(null);
  const items = useMemo(() => buildSearchItems(t), [t]);
  const results = useMemo(() => items.filter((item) => matches(item, query)).slice(0, 6), [items, query]);

  useEffect(() => {
    setQuery("");
    setOpen(false);
    setActiveIndex(0);
  }, [location.pathname]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    return () => {
      if (blurTimerRef.current !== null) {
        window.clearTimeout(blurTimerRef.current);
      }
    };
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const next = results[activeIndex] ?? results[0];
    if (next) {
      navigate(next.to, { viewTransition: true });
    }
  };

  return (
    <div className="topbar-search-wrap">
      <form className="topbar-search" role="search" onSubmit={submit}>
        <Icon name="search" className="icon-sm" />
        <input
          className="topbar-search-input"
          type="search"
          value={query}
          placeholder={t("layout.searchPlaceholder")}
          aria-label={t("layout.searchInputLabel")}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls="topbar-search-results"
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            blurTimerRef.current = window.setTimeout(() => setOpen(false), 120);
          }}
          onKeyDown={(event) => {
            if (!open || results.length === 0) {
              if (event.key === "Escape") {
                setOpen(false);
              }
              return;
            }
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setActiveIndex((current) => (current + 1) % results.length);
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              setActiveIndex((current) => (current - 1 + results.length) % results.length);
            }
            if (event.key === "Escape") {
              setOpen(false);
            }
          }}
        />
      </form>
      {open ? (
        <div className="topbar-search-panel" id="topbar-search-results" role="listbox">
          {results.length > 0 ? (
            results.map((item, index) => (
              <button
                key={item.id}
                className={`topbar-search-result${index === activeIndex ? " active" : ""}`}
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => {
                  void preloadRoute(item.to);
                }}
                onFocus={() => {
                  void preloadRoute(item.to);
                }}
                onClick={() => navigate(item.to, { viewTransition: true })}
              >
                <span className="topbar-search-result-label">{item.label}</span>
                <span className="topbar-search-result-meta">{item.meta}</span>
              </button>
            ))
          ) : (
            <div className="topbar-search-empty">{t("layout.searchNoResults")}</div>
          )}
        </div>
      ) : null}
    </div>
  );
}
