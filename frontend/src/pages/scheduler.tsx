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
  const { t, formatDateTime, formatNumber } = useI18n();
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

  const schedules = list.data ?? [];
  const statusLabel = (status: string) => (
    status === "active" || status === "paused" ? t(`scheduler.status.${status}`) : status
  );

  return (
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.scheduler")}</p>
          <h1 className="page-title">{t("scheduler.scheduledTasks")}</h1>
          <p className="page-subtitle">{t("scheduler.subtitle", {
            count: formatNumber(schedules.length),
          })}</p>
        </div>
      </section>

      <div className="split-layout">
        <section className="surface-panel panel-stack">
          <h2 className="surface-panel-title">{t("scheduler.createTask")}</h2>
          <div>
            <label className="field-label">{t("scheduler.name")}</label>
            <input className="input" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div>
            <label className="field-label">{t("scheduler.prompt")}</label>
            <textarea className="textarea" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
          </div>
          <div>
            <label className="field-label">{t("scheduler.cron")}</label>
            <input className="input mono" value={cron} onChange={(event) => setCron(event.target.value)} />
          </div>
          <button className="btn" type="button" onClick={() => create.mutate()}>
            {t("scheduler.create")}
          </button>
        </section>

        <section className="surface-panel">
          <table className="table">
            <thead>
              <tr>
                <th>{t("scheduler.table.name")}</th>
                <th>{t("scheduler.table.cron")}</th>
                <th>{t("scheduler.table.status")}</th>
                <th>{t("scheduler.table.nextRun")}</th>
                <th style={{ width: 140 }} />
              </tr>
            </thead>
            <tbody>
              {schedules.map((item) => {
                const editing = editingId === item.id;
                return (
                  <tr key={item.id}>
                    <td>
                      {editing ? (
                        <input className="input" value={editName} onChange={(event) => setEditName(event.target.value)} />
                      ) : item.name}
                    </td>
                    <td className="mono">
                      {editing ? (
                        <input className="input mono" value={editCron} onChange={(event) => setEditCron(event.target.value)} />
                      ) : item.cron}
                    </td>
                    <td>
                      <span className={`status-badge ${item.status === "active" ? "stable" : "degraded"}`}>
                        {statusLabel(item.status)}
                      </span>
                    </td>
                    <td className="mono">
                      {item.next_run_at
                        ? formatDateTime(item.next_run_at, { dateStyle: "medium", timeStyle: "short" })
                        : "-"}
                    </td>
                    <td>
                      <div className="panel-stack">
                        {editing ? (
                          <>
                            <textarea
                              className="textarea"
                              value={editPrompt}
                              onChange={(event) => setEditPrompt(event.target.value)}
                            />
                            <button
                              className="btn secondary"
                              type="button"
                              onClick={() => update.mutate({
                                id: item.id,
                                body: { name: editName, prompt: editPrompt, cron: editCron },
                              })}
                            >
                              {t("scheduler.save")}
                            </button>
                            <button className="btn ghost" type="button" onClick={() => setEditingId("")}>
                              {t("scheduler.cancel")}
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              className="btn secondary"
                              type="button"
                              onClick={() => update.mutate({
                                id: item.id,
                                body: { status: item.status === "active" ? "paused" : "active" },
                              })}
                            >
                              {item.status === "active" ? t("scheduler.pause") : t("scheduler.activate")}
                            </button>
                            <button
                              className="btn ghost"
                              type="button"
                              onClick={() => {
                                setEditingId(item.id);
                                setEditName(item.name);
                                setEditPrompt(item.prompt);
                                setEditCron(item.cron);
                              }}
                            >
                              {t("scheduler.edit")}
                            </button>
                            <button className="btn danger" type="button" onClick={() => remove.mutate(item.id)}>
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
    </div>
  );
}
