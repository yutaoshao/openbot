import { useEffect, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
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
  const { t, formatDateTime } = useI18n();
  const defaults = useMemo(
    () => ({
      name: t("scheduler.defaultName"),
      prompt: t("scheduler.defaultPrompt"),
      cron: "0 8 * * *",
    }),
    [t],
  );
  const previousDefaultsRef = useRef(defaults);
  const [name, setName] = useState(defaults.name);
  const [prompt, setPrompt] = useState(defaults.prompt);
  const [cron, setCron] = useState(defaults.cron);
  const [editingId, setEditingId] = useState("");
  const [editName, setEditName] = useState("");
  const [editPrompt, setEditPrompt] = useState("");
  const [editCron, setEditCron] = useState("");
  const qc = useQueryClient();

  useEffect(() => {
    const previousDefaults = previousDefaultsRef.current;
    setName((current) => (current === previousDefaults.name ? defaults.name : current));
    setPrompt((current) => (current === previousDefaults.prompt ? defaults.prompt : current));
    setCron((current) => (current === previousDefaults.cron ? defaults.cron : current));
    previousDefaultsRef.current = defaults;
  }, [defaults]);

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

  const statusLabel = (status: string) => {
    if (status === "active" || status === "paused") {
      return t(`scheduler.status.${status}`);
    }
    return status;
  };

  return (
    <div className="grid" style={{ gridTemplateColumns: "1fr 2fr" }}>
      <section className="card">
        <h3>{t("scheduler.createTask")}</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          <div>
            <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>{t("scheduler.name")}</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>{t("scheduler.prompt")}</label>
            <textarea className="textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </div>
          <div>
            <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>{t("scheduler.cron")}</label>
            <input className="input mono" value={cron} onChange={(e) => setCron(e.target.value)} />
          </div>
          <button className="btn" type="button" onClick={() => create.mutate()}>
            {t("scheduler.create")}
          </button>
        </div>
      </section>
      <section className="card">
        <h3>{t("scheduler.scheduledTasks")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("scheduler.table.name")}</th>
              <th>{t("scheduler.table.cron")}</th>
              <th>{t("scheduler.table.status")}</th>
              <th>{t("scheduler.table.nextRun")}</th>
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
                      {statusLabel(item.status)}
                    </span>
                  </td>
                  <td className="mono" style={{ color: "var(--text-muted)" }}>
                    {item.next_run_at ? formatDateTime(item.next_run_at, { dateStyle: "medium", timeStyle: "short" }) : "-"}
                  </td>
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
                            {t("scheduler.save")}
                          </button>
                          <button className="btn secondary" onClick={() => setEditingId("")} type="button">
                            {t("scheduler.cancel")}
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
                            {item.status === "active" ? t("scheduler.pause") : t("scheduler.activate")}
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
                            {t("scheduler.edit")}
                          </button>
                          <button className="btn danger" onClick={() => remove.mutate(item.id)} type="button">
                            {t("scheduler.delete")}
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
