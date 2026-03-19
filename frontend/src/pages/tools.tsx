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
          <p style={{ margin: "6px 0", color: "var(--muted)" }}>{tool.description}</p>
          <p className="mono">category: {tool.category}</p>
          <p className="mono">last_used: {tool.last_used || "-"}</p>
          <p className="mono">status: {tool.enabled ? "enabled" : "disabled"}</p>
          <pre className="mono" style={{ whiteSpace: "pre-wrap", background: "var(--panel-soft)", padding: 8, borderRadius: 8 }}>
            {JSON.stringify(tool.config ?? {}, null, 2)}
          </pre>
          <button className="btn secondary" onClick={() => toggle.mutate(tool)} type="button">
            {tool.enabled ? "Disable" : "Enable"}
          </button>
        </section>
      ))}
    </div>
  );
}
