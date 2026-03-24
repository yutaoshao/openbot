import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

  return (
    <div className="grid">
      {(list.data ?? []).map((tool) => (
        <section className="card" key={tool.name}>
          <h3>{tool.name}</h3>
          <p style={{ margin: "var(--space-1) 0 var(--space-3)", color: "var(--text-muted)", fontSize: 13 }}>
            {tool.description}
          </p>
          <div className="mono" style={{ color: "var(--text-dim)", display: "flex", flexDirection: "column", gap: 2, marginBottom: "var(--space-3)" }}>
            <span>category: {tool.category}</span>
            <span>last used: {tool.last_used || "never"}</span>
            <span>
              status:{" "}
              <span style={{ color: tool.enabled ? "var(--success)" : "var(--text-dim)" }}>
                {tool.enabled ? "enabled" : "disabled"}
              </span>
            </span>
          </div>
          <pre className="code-block">
            {JSON.stringify(tool.config ?? {}, null, 2)}
          </pre>
          <button
            className="btn secondary"
            onClick={() => toggle.mutate(tool)}
            type="button"
            style={{ marginTop: "var(--space-3)" }}
          >
            {tool.enabled ? "Disable" : "Enable"}
          </button>
        </section>
      ))}
    </div>
  );
}
