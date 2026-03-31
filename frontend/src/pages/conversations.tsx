import { useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";

type Conversation = {
  id: string;
  title: string | null;
  summary: string | null;
  platform: string;
  updated_at: string;
  message_count: number;
};

type Detail = {
  conversation: Conversation;
  messages: Array<{ id: string; role: string; content: string; created_at: string }>;
};

export function ConversationsPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const [query, setQuery] = useState("");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string>("");
  const qc = useQueryClient();

  const list = useQuery({
    queryKey: ["conversations", query],
    queryFn: () =>
      api.get<Conversation[]>(
        query ? `/api/conversations?q=${encodeURIComponent(query)}` : "/api/conversations",
      ),
  });

  const detail = useQuery({
    queryKey: ["conversation", selectedId],
    enabled: !!selectedId,
    queryFn: () => api.get<Detail>(`/api/conversations/${selectedId}`),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/conversations/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["conversations"] });
      setSelectedId("");
    },
  });

  const conversations = useMemo(() => {
    const rows = list.data ?? [];
    if (platformFilter === "all") return rows;
    return rows.filter((item) => item.platform === platformFilter);
  }, [list.data, platformFilter]);

  const platforms = useMemo(() => {
    const set = new Set((list.data ?? []).map((item) => item.platform));
    return ["all", ...Array.from(set)];
  }, [list.data]);

  const roleLabel = (role: string) => {
    if (role === "user" || role === "assistant") {
      return t(`chat.role.${role}`);
    }
    return role;
  };

  return (
    <div className="grid" style={{ gridTemplateColumns: "320px 1fr" }}>
      <section className="card">
        <h3>{t("conversations.title")}</h3>
        <input
          className="input"
          placeholder={t("conversations.search")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="select"
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value)}
          style={{ marginTop: "var(--space-2)" }}
        >
          {platforms.map((item) => (
            <option key={item} value={item}>
              {item === "all" ? t("conversations.allPlatforms") : item}
            </option>
          ))}
        </select>
        <div style={{ marginTop: "var(--space-3)" }}>
          {conversations.map((item) => (
            <div
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") setSelectedId(item.id); }}
              style={{
                padding: "var(--space-2) var(--space-3)",
                marginBottom: 2,
                borderRadius: "var(--radius-sm)",
                cursor: "pointer",
                background: selectedId === item.id ? "var(--hover)" : "transparent",
                transition: "background-color 150ms ease",
              }}
            >
              <div style={{ fontSize: 14, color: "var(--text)" }}>
                {item.title || item.id.slice(0, 10)}
              </div>
              <div className="mono" style={{ color: "var(--text-dim)", marginTop: 2 }}>
                {item.platform} / {t("conversations.messages", { count: formatNumber(item.message_count) })}
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="card">
        <h3>{t("conversations.detail")}</h3>
        {!selectedId ? <p style={{ color: "var(--text-muted)" }}>{t("conversations.selectPrompt")}</p> : null}
        {detail.data ? (
          <>
            <p className="mono" style={{ margin: "0 0 var(--space-1)", color: "var(--text-dim)" }}>
              {detail.data.conversation.id}
            </p>
            <p className="mono" style={{ margin: "0 0 var(--space-3)", color: "var(--text-muted)" }}>
              {t("conversations.updatedAt", {
                platform: detail.data.conversation.platform,
                time: formatDateTime(detail.data.conversation.updated_at, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </p>
            <button className="btn danger" onClick={() => remove.mutate(selectedId)} type="button">
              {t("memory.delete")}
            </button>
            <table className="table" style={{ marginTop: "var(--space-3)" }}>
              <thead>
                <tr>
                  <th style={{ width: 80 }}>{t("conversations.table.role")}</th>
                  <th>{t("conversations.table.message")}</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.messages.map((msg) => (
                  <tr key={msg.id}>
                    <td className="mono" style={{ color: msg.role === "user" ? "var(--text)" : "var(--text-muted)" }}>{roleLabel(msg.role)}</td>
                    <td style={{ whiteSpace: "pre-wrap" }}>{msg.content}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </section>
    </div>
  );
}
