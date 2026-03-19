import { useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

  return (
    <div className="grid" style={{ gridTemplateColumns: "320px 1fr" }}>
      <section className="card">
        <h3>Conversations</h3>
        <input
          className="input"
          placeholder="Search..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="select"
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value)}
          style={{ marginTop: 8 }}
        >
          {platforms.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
        <div style={{ marginTop: 10 }}>
          {conversations.map((item) => (
            <button
              key={item.id}
              className="btn secondary"
              style={{ width: "100%", marginBottom: 6, textAlign: "left" }}
              onClick={() => setSelectedId(item.id)}
              type="button"
            >
              <strong style={{ fontSize: 14 }}>{item.title || item.id.slice(0, 10)}</strong>
              <div style={{ fontSize: 12, color: "var(--muted)" }}>
                {item.platform} · {item.message_count} msgs
              </div>
            </button>
          ))}
        </div>
      </section>
      <section className="card">
        <h3>Conversation Detail</h3>
        {!selectedId ? <p>Select a conversation.</p> : null}
        {detail.data ? (
          <>
            <p className="mono">id: {detail.data.conversation.id}</p>
            <p className="mono">
              {detail.data.conversation.platform} · {new Date(detail.data.conversation.updated_at).toLocaleString()}
            </p>
            <button className="btn secondary" onClick={() => remove.mutate(selectedId)} type="button">
              Delete Conversation
            </button>
            <table className="table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.messages.map((msg) => (
                  <tr key={msg.id}>
                    <td>{msg.role}</td>
                    <td>{msg.content}</td>
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
