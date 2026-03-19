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
  const [theme, setTheme] = useState(localStorage.getItem("openbot_theme") || "light");

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

  useEffect(() => {
    localStorage.setItem("openbot_theme", theme);
    document.body.dataset.theme = theme;
  }, [theme]);

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
    <section className="card">
      <h3>Runtime Settings</h3>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <label style={{ display: "block", marginBottom: 6 }}>Telegram mode</label>
          <select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="polling">polling</option>
            <option value="webhook">webhook</option>
          </select>
        </div>
        <div>
          <label style={{ display: "block", marginBottom: 6 }}>Model max retries</label>
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
      <label style={{ display: "block", marginTop: 10 }}>
        <input
          type="checkbox"
          checked={streaming}
          onChange={(e) => setStreaming(e.target.checked)}
          style={{ marginRight: 8 }}
        />
        Enable Telegram streaming drafts
      </label>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
        <div>
          <h3 style={{ marginBottom: 6 }}>API Keys (masked)</h3>
          <p className="mono">primary ({settings.data?.model.primary.api_key_env}): {mask}</p>
          {settings.data?.model.fallback ? (
            <p className="mono">fallback ({settings.data.model.fallback.api_key_env}): {mask}</p>
          ) : null}
          <p className="mono">telegram ({settings.data?.telegram.bot_token_env}): {mask}</p>
        </div>
        <div>
          <h3 style={{ marginBottom: 6 }}>Theme Preference</h3>
          <select className="select" value={theme} onChange={(e) => setTheme(e.target.value)}>
            <option value="light">Light</option>
            <option value="paper">Paper</option>
          </select>
        </div>
      </div>
      <button className="btn" type="button" onClick={() => update.mutate()} style={{ marginTop: 12 }}>
        Save
      </button>
      <pre className="mono" style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>
        {JSON.stringify(settings.data ?? {}, null, 2)}
      </pre>
    </section>
  );
}
