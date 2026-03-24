import { useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

type Schedule = {
  id: string;
  name: string;
  prompt: string;
  cron: string;
  status: string;
  next_run_at?: string | null;
};

type SchedulePatch = {
  name?: string;
  prompt?: string;
  cron?: string;
  status?: string;
};

export function SchedulerPage(): JSX.Element {
  const [name, setName] = useState("Daily Summary");
  const [prompt, setPrompt] = useState("Summarize today's conversations");
  const [cron, setCron] = useState("0 8 * * *");
  const [editingId, setEditingId] = useState("");
  const [editName, setEditName] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editCron, setEditCron] = useState("");
  const qc = useQueryClient();

  const list = useQuery({
    queryKey: ["schedules"],
    queryFn: () => api.get<Schedule[]>("/api/schedules"),
  });

  const create = useMutation({
    mutationFn: () => api.post<Schedule>("/api/schedules", { name, prompt, cron, status: "active" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["schedules"] });
    },
  });

  const update = useMutation({
    mutationFn: (payload: { id: string; body: SchedulePatch }) =>
      api.put<Schedule>(`/api/schedules/${payload.id}`, payload.body),
    onSuccess: () => {
      setEditingId("");
      void qc.invalidateQueries({ queryKey: ["schedules"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/schedules/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["schedules"] });
    },
  });

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 2fr" }}>
      <section className="card">
        <h3>Create Task</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          <div>
            <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>Name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>Prompt</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </div>
          <div>
            <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>Cron</label>
            <input className="input mono" value={cron} onChange={(e) => setCron(e.target.value)} />
          </div>
          <button className="btn" type="button" onClick={() => create.mutate()}>
            Create
          </button>
        </div>
      </section>
      <section className="card">
        <h3>Scheduled Tasks</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Cron</th>
              <th>Status</th>
              <th>Next Run</th>
              <th style={{ width: 120 }} />
            </tr>
          </thead>
          <tbody>
            {(list.data ?? []).map((item) => {
              const editing = editingId === item.id;
              return (
                <tr key={item.id}>
                  <td>
                    {editing ? (
                      <input className="input" value={editName} onChange={(e) => setEditName(e.target.value)} />
                    ) : (
                      item.name
                    )}
                  </td>
                  <td className="mono">
                    {editing ? (
                      <input className="input mono" value={editCron} onChange={(e) => setEditCron(e.target.value)} />
                    ) : (
                      item.cron
                    )}
                  </td>
                  <td>
                    <span style={{ color: item.status === "active" ? "var(--success)" : "var(--text-dim)" }}>
                      {item.status}
                    </span>
                  </td>
                  <td className="mono" style={{ color: "var(--text-muted)" }}>{item.next_run_at || "-"}</td>
                  <td>
                    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
                      {editing ? (
                        <>
                          <textarea
                            className="textarea"
                            value={editPrompt}
                            onChange={(e) => setEditPrompt(e.target.value)}
                            style={{ minHeight: 60 }}
                          />
                          <button
                            className="btn secondary"
                            onClick={() => update.mutate({ id: item.id, body: { name: editName, prompt: editPrompt, cron: editCron } })}
                            type="button"
                          >
                            Save
                          </button>
                          <button className="btn secondary" onClick={() => setEditingId("")} type="button">
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="btn secondary"
                            onClick={() =>
                              update.mutate({
                                id: item.id,
                                body: { status: item.status === "active" ? "paused" : "active" },
                              })
                            }
                            type="button"
                          >
                            {item.status === "active" ? "Pause" : "Activate"}
                          </button>
                          <button
                            className="btn secondary"
                            onClick={() => {
                              setEditingId(item.id);
                              setEditName(item.name);
                              setEditPrompt(item.prompt);
                              setEditCron(item.cron);
                            }}
                            type="button"
                          >
                            Edit
                          </button>
                          <button className="btn danger" onClick={() => remove.mutate(item.id)} type="button">
                            Delete
                          </button>
                        </>
                      )}
                    </div>
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
