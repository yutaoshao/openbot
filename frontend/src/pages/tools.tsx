import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import { isDesktopDemoPath } from "../demo/location";
import { isDesktopPath } from "../desktop/location";
import { authorizeExecution, type ExecutionTool } from "../desktop/ExecutionPermissions";
import { useDesktopStatus } from "../desktop/DesktopSettings";

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
  const [authorization, setAuthorization] = useState<ToolItem | null>(null);
  const live = isDesktopPath(window.location.pathname);
  const status = useDesktopStatus(live);
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
  const grant = useMutation({
    mutationFn: (tool: ToolItem) => authorizeExecution(tool.name as ExecutionTool, true),
    onSuccess: () => {
      setAuthorization(null);
      void qc.invalidateQueries({ queryKey: ["tools"] });
      void qc.invalidateQueries({ queryKey: ["desktop-status"] });
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

      {authorization && <section className="surface-panel demo-permission-review" role="dialog"
        aria-labelledby="demo-permission-title">
        <h2 id="demo-permission-title">{t("desktop.executionTitle", { tool: authorization.name })}</h2>
        <p>{t("desktop.executionDetail")}</p>
        <p className="field-help">{t(live ? "desktopLive.executionHint" : "desktop.executionPreview")}</p>
        <div className="filter-row">
          <button className="btn" type="button" disabled={grant.isPending} onClick={() => {
            if (live) grant.mutate(authorization);
            else { toggle.mutate(authorization); setAuthorization(null); }
          }}>
            {t("desktop.executionAllow")}
          </button>
          <button className="btn secondary" type="button" onClick={() => setAuthorization(null)}>
            {t("desktop.executionCancel")}
          </button>
        </div>
      </section>}
      {(toggle.error || grant.error) && <p role="alert">{(toggle.error || grant.error)?.message}</p>}

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
              disabled={toggle.isPending || grant.isPending}
              onClick={() => {
                const needsLiveGrant = live && ["bash", "code_executor"].includes(tool.name)
                  && !status.data?.permissions[tool.name as ExecutionTool];
                if (!tool.enabled && (needsLiveGrant || (isDesktopDemoPath(window.location.pathname) && ["bash", "python"].includes(tool.name)))) {
                  setAuthorization(tool);
                } else toggle.mutate(tool);
              }}
            >
              {tool.enabled ? t("tools.disable") : t("tools.enable")}
            </button>
          </section>
        ))}
      </div>
    </div>
  );
}
