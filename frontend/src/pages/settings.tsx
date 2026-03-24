import { useEffect, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";

type Settings = {
  telegram: {
    enable_streaming: boolean;
    mode: string;
    bot_token_env: string;
  };
  model: {
    max_retries: number;
    primary: {
      model: string;
      api_key_env: string;
    };
    fallback: {
      model: string;
      api_key_env: string;
    } | null;
  };
};

export function SettingsPage(): JSX.Element {
  const qc = useQueryClient();
  const [streaming, setStreaming] = useState(false);
  const [mode, setMode] = useState("polling");
  const [maxRetries, setMaxRetries] = useState(3);

  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<Settings>("/api/settings"),
  });

  useEffect(() => {
    if (settings.data) {
      setStreaming(settings.data.telegram.enable_streaming);
      setMode(settings.data.telegram.mode);
      setMaxRetries(settings.data.model.max_retries);
    }
  }, [settings.data]);

  const update = useMutation({
    mutationFn: () =>
      api.put("/api/settings", {
        telegram: {
          enable_streaming: streaming,
          mode,
        },
        model: {
          max_retries: maxRetries,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const mask = "********";

  return (
    <section className="card" style={{ maxWidth: 800 }}>
      <h3>Settings</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)" }}>
        <div>
          <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>
            Telegram mode
          </label>
          <select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="polling">polling</option>
            <option value="webhook">webhook</option>
          </select>
        </div>
        <div>
          <label style={{ display: "block", marginBottom: "var(--space-1)", fontSize: 13, color: "var(--text-muted)" }}>
            Model max retries
          </label>
          <input
            className="input"
            type="number"
            min={0}
            max={10}
            value={maxRetries}
            onChange={(e) => setMaxRetries(Number(e.target.value))}
          />
        </div>
      </div>

      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-4)", cursor: "pointer", color: "var(--text-muted)" }}>
        <input
          type="checkbox"
          checked={streaming}
          onChange={(e) => setStreaming(e.target.checked)}
        />
        Enable Telegram streaming drafts
      </label>

      <div style={{ marginTop: "var(--space-6)", borderTop: "1px solid var(--border)", paddingTop: "var(--space-4)" }}>
        <h3>API Keys</h3>
        <div className="mono" style={{ color: "var(--text-dim)", display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span>primary ({settings.data?.model.primary.api_key_env}): {mask}</span>
          {settings.data?.model.fallback ? (
            <span>fallback ({settings.data.model.fallback.api_key_env}): {mask}</span>
          ) : null}
          <span>telegram ({settings.data?.telegram.bot_token_env}): {mask}</span>
        </div>
      </div>

      <button className="btn" type="button" onClick={() => update.mutate()} style={{ marginTop: "var(--space-4)" }}>
        Save
      </button>

      <pre className="code-block" style={{ marginTop: "var(--space-4)" }}>
        {JSON.stringify(settings.data ?? {}, null, 2)}
      </pre>
    </section>
  );
}
