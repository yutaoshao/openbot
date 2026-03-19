import { useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

type Knowledge = {
  id: string;
  category: string;
  content: string;
  priority: string;
};

export function MemoryPage(): JSX.Element {
  const qc = useQueryClient();
  const [category, setCategory] = useState("fact");
  const [priority, setPriority] = useState("P1");
  const [content, setContent] = useState("");
  const [search, setSearch] = useState("");
  const [filterCategory, setFilterCategory] = useState("all");
  const [filterPriority, setFilterPriority] = useState("all");
  const [editingId, setEditingId] = useState("");
  const [editingContent, setEditingContent] = useState("");
  const [editingPriority, setEditingPriority] = useState("P1");

  const list = useQuery({
    queryKey: ["knowledge", search, filterCategory, filterPriority],
    queryFn: async () => {
      if (search.trim()) {
        return api.get<Knowledge[]>(`/api/knowledge/search?q=${encodeURIComponent(search.trim())}`);
      }
      const params = new URLSearchParams();
      if (filterCategory !== "all") params.set("category", filterCategory);
      if (filterPriority !== "all") params.set("priority", filterPriority);
      const suffix = params.toString();
      return api.get<Knowledge[]>(`/api/knowledge${suffix ? `?${suffix}` : ""}`);
    },
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<Knowledge>("/api/knowledge", {
        category,
        content,
        priority,
      }),
    onSuccess: () => {
      setContent("");
      setPriority("P1");
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });

  const update = useMutation({
    mutationFn: (id: string) =>
      api.put<Knowledge>(`/api/knowledge/${id}`, {
        content: editingContent,
        priority: editingPriority,
      }),
    onSuccess: () => {
      setEditingId("");
      setEditingContent("");
      setEditingPriority("P1");
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/knowledge/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
  });

  const items = useMemo(() => list.data ?? [], [list.data]);

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <section className="card">
        <h3>Add Knowledge</h3>
        <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="fact">fact</option>
          <option value="concept">concept</option>
          <option value="procedure">procedure</option>
        </select>
        <select className="select" value={priority} onChange={(e) => setPriority(e.target.value)} style={{ marginTop: 8 }}>
          <option value="P1">P1</option>
          <option value="P2">P2</option>
          <option value="P3">P3</option>
        </select>
        <textarea
          className="textarea"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Knowledge content"
          style={{ marginTop: 8 }}
        />
        <button className="btn" onClick={() => create.mutate()} type="button" disabled={!content.trim()}>
          Save
        </button>
      </section>
      <section className="card">
        <h3>Knowledge Base</h3>
        <input
          className="input"
          placeholder="Search content..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
          <select className="select" value={filterCategory} onChange={(e) => setFilterCategory(e.target.value)}>
            <option value="all">all categories</option>
            <option value="fact">fact</option>
            <option value="concept">concept</option>
            <option value="procedure">procedure</option>
          </select>
          <select className="select" value={filterPriority} onChange={(e) => setFilterPriority(e.target.value)}>
            <option value="all">all priorities</option>
            <option value="P1">P1</option>
            <option value="P2">P2</option>
            <option value="P3">P3</option>
          </select>
        </div>
        <table className="table" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Category</th>
              <th>Priority</th>
              <th>Content</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const editing = editingId === item.id;
              return (
                <tr key={item.id}>
                  <td>{item.category}</td>
                  <td>
                    {editing ? (
                      <select
                        className="select"
                        value={editingPriority}
                        onChange={(e) => setEditingPriority(e.target.value)}
                      >
                        <option value="P1">P1</option>
                        <option value="P2">P2</option>
                        <option value="P3">P3</option>
                      </select>
                    ) : (
                      item.priority
                    )}
                  </td>
                  <td>
                    {editing ? (
                      <textarea
                        className="textarea"
                        value={editingContent}
                        onChange={(e) => setEditingContent(e.target.value)}
                      />
                    ) : (
                      item.content
                    )}
                  </td>
                  <td>
                    {editing ? (
                      <>
                        <button className="btn secondary" type="button" onClick={() => update.mutate(item.id)}>
                          Save
                        </button>
                        <button
                          className="btn secondary"
                          type="button"
                          style={{ marginTop: 6 }}
                          onClick={() => {
                            setEditingId("");
                            setEditingContent("");
                            setEditingPriority("P1");
                          }}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="btn secondary"
                          type="button"
                          onClick={() => {
                            setEditingId(item.id);
                            setEditingContent(item.content);
                            setEditingPriority(item.priority);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="btn secondary"
                          onClick={() => {
                            const ok = window.confirm("Delete this knowledge item?");
                            if (ok) {
                              remove.mutate(item.id);
                            }
                          }}
                          type="button"
                          style={{ marginTop: 6 }}
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </div>
  );
}
