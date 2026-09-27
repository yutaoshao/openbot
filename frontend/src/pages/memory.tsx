import { useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";

type Knowledge = {
  id: string;
  category: string;
  content: string;
  priority: string;
};

type ProfileDocument = { name: string; content: string; revision: string };

export function MemoryPage(): JSX.Element {
  const { t, formatNumber } = useI18n();
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
  const [selectedProfile, setSelectedProfile] = useState("");
  const [profileContent, setProfileContent] = useState<string | null>(null);

  const profileList = useQuery({
    queryKey: ["personal-memory"],
    queryFn: () => api.get<{ documents: string[] }>("/api/personal-memory"),
  });
  const profileDocument = useQuery({
    queryKey: ["personal-memory", selectedProfile],
    queryFn: () => api.get<ProfileDocument>(`/api/personal-memory/${selectedProfile.split("/").map(encodeURIComponent).join("/")}`),
    enabled: Boolean(selectedProfile),
  });
  const saveProfile = useMutation({
    mutationFn: () => api.put<ProfileDocument>(
      `/api/personal-memory/${selectedProfile.split("/").map(encodeURIComponent).join("/")}`,
      { content: profileContent, revision: profileDocument.data?.revision ?? "" },
    ),
    onSuccess: (updated) => {
      qc.setQueryData(["personal-memory", selectedProfile], updated);
      setProfileContent(null);
      void qc.invalidateQueries({ queryKey: ["personal-memory"] });
    },
  });

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
  const categoryLabel = (value: string) => {
    const key = `memory.category.${value}`;
    return t(key) === key ? value : t(key);
  };

  return (
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.memory")}</p>
          <h1 className="page-title">{t("memory.knowledgeBase")}</h1>
          <p className="page-subtitle">{t("memory.subtitle", {
            count: formatNumber(items.length),
          })}</p>
        </div>
      </section>

      <section className="surface-panel panel-stack">
        <h2 className="surface-panel-title">{t("memory.personalProfiles")}</h2>
        <p>{t("memory.personalProfilesHint")}</p>
        <select className="select" aria-label={t("memory.personalProfiles")} value={selectedProfile}
          onChange={(event) => { setSelectedProfile(event.target.value); setProfileContent(null); }}>
          <option value="">{t("memory.selectProfile")}</option>
          {(profileList.data?.documents ?? []).map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
        {selectedProfile && profileDocument.data && (
          <>
            <p>{selectedProfile}</p>
            <textarea className="textarea" rows={14} aria-label={t("memory.personalProfiles")}
              value={profileContent ?? profileDocument.data.content}
              onChange={(event) => setProfileContent(event.target.value)} />
            <button className="btn" type="button" disabled={saveProfile.isPending}
              onClick={() => saveProfile.mutate()}>{t("memory.save")}</button>
            {saveProfile.isError && <p role="alert">{saveProfile.error.message}</p>}
          </>
        )}
      </section>

      <div className="split-layout">
        <section className="surface-panel panel-stack">
          <h2 className="surface-panel-title">{t("memory.addKnowledge")}</h2>
          <select className="select" aria-label={t("memory.field.category")} value={category} onChange={(event) => setCategory(event.target.value)}>
            <option value="fact">{categoryLabel("fact")}</option>
            <option value="concept">{categoryLabel("concept")}</option>
            <option value="procedure">{categoryLabel("procedure")}</option>
          </select>
          <select className="select" aria-label={t("memory.field.priority")} value={priority} onChange={(event) => setPriority(event.target.value)}>
            <option value="P1">P1</option>
            <option value="P2">P2</option>
            <option value="P3">P3</option>
          </select>
          <textarea
            className="textarea"
            aria-label={t("memory.contentPlaceholder")}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={t("memory.contentPlaceholder")}
          />
          <button
            className="btn"
            type="button"
            disabled={!content.trim()}
            onClick={() => create.mutate()}
          >
            {t("memory.save")}
          </button>
        </section>

        <section className="surface-panel panel-stack">
          <div className="filter-row">
            <input
              className="input"
              placeholder={t("memory.search")}
              aria-label={t("memory.search")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select className="select" aria-label={t("memory.filterCategory")} value={filterCategory} onChange={(event) => setFilterCategory(event.target.value)}>
              <option value="all">{t("memory.allCategories")}</option>
              <option value="fact">{categoryLabel("fact")}</option>
              <option value="concept">{categoryLabel("concept")}</option>
              <option value="procedure">{categoryLabel("procedure")}</option>
            </select>
            <select className="select" aria-label={t("memory.filterPriority")} value={filterPriority} onChange={(event) => setFilterPriority(event.target.value)}>
              <option value="all">{t("memory.allPriorities")}</option>
              <option value="P1">P1</option>
              <option value="P2">P2</option>
              <option value="P3">P3</option>
            </select>
          </div>

          <table className="table">
            <thead>
              <tr>
                <th>{t("memory.table.category")}</th>
                <th>{t("memory.table.priority")}</th>
                <th>{t("memory.table.content")}</th>
                <th style={{ width: 120 }} />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const editing = editingId === item.id;
                return (
                  <tr key={item.id}>
                    <td className="mono">{categoryLabel(item.category)}</td>
                    <td>
                      {editing ? (
                        <select
                          className="select"
                          aria-label={t("memory.table.priority")}
                          value={editingPriority}
                          onChange={(event) => setEditingPriority(event.target.value)}
                        >
                          <option value="P1">P1</option>
                          <option value="P2">P2</option>
                          <option value="P3">P3</option>
                        </select>
                      ) : (
                        <span className="mono">{item.priority}</span>
                      )}
                    </td>
                    <td>
                      {editing ? (
                        <textarea
                          className="textarea"
                          aria-label={t("memory.table.content")}
                          value={editingContent}
                          onChange={(event) => setEditingContent(event.target.value)}
                        />
                      ) : (
                        item.content
                      )}
                    </td>
                    <td>
                      <div className="panel-stack">
                        {editing ? (
                          <>
                            <button className="btn secondary" type="button" onClick={() => update.mutate(item.id)}>
                              {t("memory.save")}
                            </button>
                            <button
                              className="btn ghost"
                              type="button"
                              onClick={() => {
                                setEditingId("");
                                setEditingContent("");
                                setEditingPriority("P1");
                              }}
                            >
                              {t("memory.cancel")}
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
                              {t("memory.edit")}
                            </button>
                            <button
                              className="btn danger"
                              type="button"
                              onClick={() => {
                                if (window.confirm(t("memory.confirmDelete"))) {
                                  remove.mutate(item.id);
                                }
                              }}
                            >
                              {t("memory.delete")}
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
