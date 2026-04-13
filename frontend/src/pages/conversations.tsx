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
  const [selectedId, setSelectedId] = useState("");
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
    return platformFilter === "all"
      ? rows
      : rows.filter((item) => item.platform === platformFilter);
  }, [list.data, platformFilter]);

  const platforms = useMemo(() => {
    const values = new Set((list.data ?? []).map((item) => item.platform));
    return ["all", ...Array.from(values)];
  }, [list.data]);

  const roleLabel = (role: string) => {
    if (role === "user" || role === "assistant") {
      return t(`chat.role.${role}`);
    }
    return role;
  };

  return (
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.conversations")}</p>
          <h1 className="page-title">{t("conversations.title")}</h1>
          <p className="page-subtitle">{t("conversations.subtitle", {
            count: formatNumber(conversations.length),
          })}</p>
        </div>
      </section>

      <div className="split-layout">
        <section className="surface-panel panel-stack">
          <div className="filter-row">
            <input
              className="input"
              placeholder={t("conversations.search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <select
              className="select"
              value={platformFilter}
              onChange={(event) => setPlatformFilter(event.target.value)}
            >
              {platforms.map((item) => (
                <option key={item} value={item}>
                  {item === "all" ? t("conversations.allPlatforms") : item}
                </option>
              ))}
            </select>
          </div>

          <div className="entity-list">
            {conversations.map((item) => (
              <div
                key={item.id}
                role="button"
                tabIndex={0}
                className={`entity-list-item${selectedId === item.id ? " active" : ""}`}
                onClick={() => setSelectedId(item.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    setSelectedId(item.id);
                  }
                }}
              >
                <p className="entity-list-title">{item.title || item.id.slice(0, 12)}</p>
                <p className="entity-list-meta">
                  {item.platform} · {t("conversations.messages", {
                    count: formatNumber(item.message_count),
                  })}
                </p>
                <p className="entity-list-meta">
                  {formatDateTime(item.updated_at, { dateStyle: "medium", timeStyle: "short" })}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section className="surface-panel">
          {!selectedId ? (
            <div className="detail-empty">{t("conversations.selectPrompt")}</div>
          ) : null}

          {detail.data ? (
            <>
              <div className="detail-summary">
                <strong>{detail.data.conversation.title || detail.data.conversation.id}</strong>
                <p>{t("conversations.updatedAt", {
                  platform: detail.data.conversation.platform,
                  time: formatDateTime(detail.data.conversation.updated_at, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                })}</p>
              </div>
              <button
                className="btn danger"
                type="button"
                onClick={() => remove.mutate(selectedId)}
              >
                {t("memory.delete")}
              </button>
              <table className="table" style={{ marginTop: "var(--space-4)" }}>
                <thead>
                  <tr>
                    <th style={{ width: 120 }}>{t("conversations.table.role")}</th>
                    <th>{t("conversations.table.message")}</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.data.messages.map((msg) => (
                    <tr key={msg.id}>
                      <td className="mono">{roleLabel(msg.role)}</td>
                      <td style={{ whiteSpace: "pre-wrap" }}>{msg.content}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}
