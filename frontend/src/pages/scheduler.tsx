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
    <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <section className="card">
        <h3>Create Task</h3>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} style={{ marginTop: 8 }} />
        <input className="input mono" value={cron} onChange={(e) => setCron(e.target.value)} style={{ marginTop: 8 }} />
        <button className="btn" type="button" onClick={() => create.mutate()}>
          Create Schedule
        </button>
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
              <th />
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
                  <td>{item.status}</td>
                  <td className="mono">{item.next_run_at || "-"}</td>
                  <td>
                    {editing ? (
                      <>
                        <textarea
                          className="textarea"
                          value={editPrompt}
                          onChange={(e) => setEditPrompt(e.target.value)}
                        />
                        <button
                          className="btn secondary"
                          onClick={() => update.mutate({ id: item.id, body: { name: editName, prompt: editPrompt, cron: editCron } })}
                          type="button"
                        >
                          Save
                        </button>
                        <button className="btn secondary" onClick={() => setEditingId("")} type="button" style={{ marginTop: 6 }}>
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
                          style={{ marginTop: 6 }}
                        >
                          Edit
                        </button>
                        <button className="btn secondary" onClick={() => remove.mutate(item.id)} type="button" style={{ marginTop: 6 }}>
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
