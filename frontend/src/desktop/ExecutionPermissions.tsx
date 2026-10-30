import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "../i18n";
import { api } from "../lib/api";
import type { DesktopStatus } from "./types";

export type ExecutionTool = "bash" | "code_executor";
export async function authorizeExecution(tool: ExecutionTool, authorized: boolean): Promise<unknown> {
  return api.post("/api/desktop/permissions", { tool, authorized, acknowledgement: "current-user-permissions" });
}

export function ExecutionPermissions({ permissions }: { permissions: DesktopStatus["permissions"] }): JSX.Element {
  const { t } = useI18n();
  const cache = useQueryClient();
  const [review, setReview] = useState<ExecutionTool | null>(null);
  const update = useMutation({
    mutationFn: ({ tool, authorized }: { tool: ExecutionTool; authorized: boolean }) => authorizeExecution(tool, authorized),
    onSuccess: () => {
      setReview(null);
      void cache.invalidateQueries({ queryKey: ["desktop-status"] });
      void cache.invalidateQueries({ queryKey: ["tools"] });
    },
  });
  return <section className="surface-panel settings-section">
    <h2>{t("desktopLive.execution")}</h2>
    <p className="field-help">{t("desktopLive.executionHint")}</p>
    <div className="settings-grid">
      {(["bash", "code_executor"] as const).map((tool) => <label className="toggle-card" key={tool}>
        <div><span className="field-label">{tool === "bash" ? "Shell" : "Python"}</span>
          <p className="field-help">{t(permissions[tool] ? "desktopLive.authorized" : "desktopLive.notAuthorized")}</p></div>
        <input type="checkbox" checked={permissions[tool]} disabled={update.isPending}
          onChange={(event) => {
            if (event.target.checked) setReview(tool);
            else update.mutate({ tool, authorized: false });
          }} />
      </label>)}
    </div>
    {review && <div className="demo-permission-review" role="dialog" aria-labelledby="live-permission-title">
      <h3 id="live-permission-title">{t("desktop.executionTitle", { tool: review === "bash" ? "Shell" : "Python" })}</h3>
      <p>{t("desktop.executionDetail")}</p><p className="field-help">{t("desktopLive.executionHint")}</p>
      <div className="filter-row">
        <button className="btn" type="button" disabled={update.isPending}
          onClick={() => update.mutate({ tool: review, authorized: true })}>{t("desktop.executionAllow")}</button>
        <button className="btn secondary" type="button" disabled={update.isPending} onClick={() => setReview(null)}>{t("desktop.executionCancel")}</button>
      </div>
    </div>}
    {update.error && <p role="alert">{update.error.message}</p>}
  </section>;
}
