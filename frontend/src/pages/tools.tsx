import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";

type ToolItem = {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  config: Record<string, unknown>;
  last_used: string | null;
};

export function ToolsPage(): JSX.Element {
  const { t, formatDateTime, formatNumber } = useI18n();
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["tools"],
    queryFn: () => api.get<ToolItem[]>("/api/tools"),
  });

  const toggle = useMutation({
    mutationFn: (tool: ToolItem) =>
      api.put(`/api/tools/${tool.name}/config`, {
        enabled: !tool.enabled,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tools"] });
    },
  });

  const tools = list.data ?? [];

  return (
    <div className="stack-layout">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.tools")}</p>
          <h1 className="page-title">{t("nav.tools")}</h1>
          <p className="page-subtitle">{t("tools.subtitle", {
            count: formatNumber(tools.length),
          })}</p>
        </div>
      </section>

      <div className="tool-grid">
        {tools.map((tool) => (
          <section className="surface-panel tool-card" key={tool.name}>
            <div className="tool-card-header">
              <div>
                <h3>{tool.name}</h3>
                <p>{tool.description}</p>
              </div>
              <span className={`status-badge ${tool.enabled ? "stable" : "degraded"}`}>
                {tool.enabled ? t("tools.enabled") : t("tools.disabled")}
              </span>
            </div>

            <div className="meta-list">
              <span>{t("tools.category")}: {tool.category}</span>
              <span>
                {t("tools.lastUsed")}: {tool.last_used
                  ? formatDateTime(tool.last_used, { dateStyle: "medium", timeStyle: "short" })
                  : t("tools.never")}
              </span>
            </div>

            <pre className="code-block">{JSON.stringify(tool.config ?? {}, null, 2)}</pre>

            <button
              className="btn secondary"
              type="button"
              onClick={() => toggle.mutate(tool)}
            >
              {tool.enabled ? t("tools.disable") : t("tools.enable")}
            </button>
          </section>
        ))}
      </div>
    </div>
  );
}
