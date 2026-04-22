import { useEffect, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Icon } from "../components/Icon";
import { SettingsSectionHeader } from "../components/SettingsSectionHeader";
import { useI18n, type Language } from "../i18n";
import { api } from "../lib/api";
import { operatorQueryDefaults } from "../lib/query-defaults";
import {
  buildSecrets,
  formatRestartReasons,
  secretValueMap,
  syncDraft,
  type SecretRow,
  type SecretValue,
  type Settings,
} from "../lib/settings-view";

type SettingsUpdateResponse = {
  settings: Omit<Settings, "runtime" | "restart_required" | "restart_reasons">;
  runtime: Settings["runtime"];
  restart_required: boolean;
  restart_reasons: string[];
};

type SettingsSecretsResponse = {
  secrets: SecretValue[];
};

type SettingsApplyResponse = {
  status: "restarting";
  restart_required: boolean;
  restart_reasons: string[];
};

export function SettingsPage(): JSX.Element {
  const qc = useQueryClient();
  const { language, setLanguage, t } = useI18n();
  const [enabled, setEnabled] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [mode, setMode] = useState("polling");
  const [maxRetries, setMaxRetries] = useState(3);
  const [showSecretValues, setShowSecretValues] = useState(false);
  const [revealedSecrets, setRevealedSecrets] = useState<SecretValue[]>([]);
  const [restartPending, setRestartPending] = useState(false);

  const settings = useQuery({
    ...operatorQueryDefaults,
    queryKey: ["settings"],
    queryFn: () => api.get<Settings>("/api/settings"),
  });

  useEffect(() => {
    if (settings.data) {
      syncDraft(settings.data, {
        setEnabled,
        setMode,
        setStreaming,
        setMaxRetries,
      });
    }
  }, [settings.data]);

  const update = useMutation({
    mutationFn: () =>
      api.put<SettingsUpdateResponse>("/api/settings", {
        telegram: {
          enabled,
          enable_streaming: streaming,
          mode,
        },
        model: {
          max_retries: maxRetries,
        },
      }),
    onSuccess: (response) => {
      qc.setQueryData<Settings>(["settings"], {
        ...response.settings,
        runtime: response.runtime,
        restart_required: response.restart_required,
        restart_reasons: response.restart_reasons,
      });
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
  const revealSecrets = useMutation({
    mutationFn: () => api.get<SettingsSecretsResponse>("/api/settings/secrets"),
    onSuccess: (response) => {
      setRevealedSecrets(response.secrets);
      setShowSecretValues(true);
    },
  });
  const applySavedSettings = useMutation({
    mutationFn: () => api.post<SettingsApplyResponse>("/api/settings/apply", {}),
    onSuccess: () => {
      setRestartPending(true);
      window.setTimeout(() => {
        window.location.reload();
      }, 1500);
    },
  });

  const isDirty = settings.data
    ? settings.data.telegram.enabled !== enabled
      || settings.data.telegram.enable_streaming !== streaming
      || settings.data.telegram.mode !== mode
      || settings.data.model.max_retries !== maxRetries
    : false;

  const secrets = useMemo<SecretRow[]>(() => (
    settings.data ? buildSecrets(settings.data, t) : []
  ), [settings.data, t]);
  const restartReasons = useMemo<string[]>(() => (
    settings.data ? formatRestartReasons(settings.data, t) : []
  ), [settings.data, t]);
  const saveError = update.error instanceof Error ? update.error.message : "";
  const applyError = applySavedSettings.error instanceof Error ? applySavedSettings.error.message : "";
  const secretValues = useMemo(
    () => secretValueMap(revealedSecrets),
    [revealedSecrets],
  );
  const statusText = restartPending
    ? t("settings.restartingFooter")
    : settings.data?.restart_required
      ? t("settings.restartRequiredFooter")
      : isDirty
        ? t("settings.unsavedChanges")
        : t("settings.savedToConfig");

  return (
    <div className="settings-page">
      <section className="page-header">
        <div>
          <p className="page-eyebrow">{t("nav.settings")}</p>
          <h1 className="page-title">{t("settings.title")}</h1>
          <p className="page-subtitle">{t("settings.subtitle")}</p>
        </div>
      </section>

      <div className="settings-shell">
        <nav className="settings-nav surface-panel">
          <a className="settings-nav-link active" href="#general">{t("settings.general")}</a>
          <a className="settings-nav-link" href="#connectivity">{t("settings.connectivity")}</a>
          <a className="settings-nav-link" href="#inference">{t("settings.inference")}</a>
          <a className="settings-nav-link" href="#secrets">{t("settings.secrets")}</a>
        </nav>

        <div className="settings-content">
          <section className="surface-panel settings-section" id="general">
            <SettingsSectionHeader icon="spark" title={t("settings.general")} description={t("settings.generalHint")} />
            <div className="settings-grid">
              <div className="field-card">
                <label className="field-label">{t("settings.language")}</label>
                <select
                  className="select"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value as Language)}
                >
                  <option value="zh-CN">{t("settings.language.zh-CN")}</option>
                  <option value="en-US">{t("settings.language.en-US")}</option>
                </select>
                <p className="field-help">{t("settings.languageLocalHint")}</p>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.localOnly")}</label>
                <div className="settings-runtime-value">
                  {settings.data
                    ? settings.data.api.local_only
                      ? t("settings.localOnlyEnabled")
                      : t("settings.localOnlyDisabled")
                    : "-"}
                </div>
                <p className="field-help">{t("settings.localOnlyHint")}</p>
              </div>
            </div>
          </section>

          <section className="surface-panel settings-section" id="connectivity">
            <SettingsSectionHeader icon="shield" title={t("settings.connectivity")} description={t("settings.connectivityHint")} />
            <div className="settings-grid">
              <div className="field-card">
                <label className="field-label">{t("settings.telegramEnabled")}</label>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  <label className="toggle-card" htmlFor="telegram-enabled">
                    <div>
                      <span className="field-label">{t("settings.telegramEnabled")}</span>
                      <p className="field-help">{t("settings.telegramEnabledHint")}</p>
                    </div>
                    <input
                      id="telegram-enabled"
                      checked={enabled}
                      type="checkbox"
                      onChange={(event) => setEnabled(event.target.checked)}
                    />
                  </label>
                </div>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.telegramMode")}</label>
                <select className="select" value={mode} onChange={(event) => setMode(event.target.value)}>
                  <option value="polling">polling</option>
                  <option value="webhook">webhook</option>
                </select>
              </div>
              <label className="toggle-card" htmlFor="telegram-streaming">
                <div>
                  <span className="field-label">{t("settings.enableStreaming")}</span>
                  <p className="field-help">{t("settings.streamingHint")}</p>
                </div>
                <input
                  id="telegram-streaming"
                  checked={streaming}
                  type="checkbox"
                  onChange={(event) => setStreaming(event.target.checked)}
                />
              </label>
              <div className="field-card">
                <label className="field-label">{t("settings.telegramStatus")}</label>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  <span
                    className={`status-badge ${
                      settings.data?.runtime.telegram.status === "ready" ? "stable" : "degraded"
                    }`}
                  >
                    {settings.data?.runtime.telegram.status ?? "-"}
                  </span>
                  {settings.data?.runtime.telegram.missing_env_vars.length ? (
                    <p className="field-help">
                      {t("settings.telegramMissing", {
                        envs: settings.data.runtime.telegram.missing_env_vars.join(", "),
                      })}
                    </p>
                  ) : (
                    <p className="field-help">{t("settings.telegramStatusHint")}</p>
                  )}
                </div>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.feishuMode")}</label>
                <div className="settings-runtime-value">{settings.data?.feishu.mode ?? "-"}</div>
                <p className="field-help">{t("settings.feishuModeHint")}</p>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.feishuStatus")}</label>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  <span
                    className={`status-badge ${
                      settings.data?.runtime.feishu.status === "ready" ? "stable" : "degraded"
                    }`}
                  >
                    {settings.data?.runtime.feishu.status ?? "-"}
                  </span>
                  {settings.data?.runtime.feishu.missing_env_vars.length ? (
                    <p className="field-help">
                      {t("settings.feishuMissing", {
                        envs: settings.data.runtime.feishu.missing_env_vars.join(", "),
                      })}
                    </p>
                  ) : (
                    <p className="field-help">{t("settings.feishuStatusHint")}</p>
                  )}
                </div>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.wechatMode")}</label>
                <div className="settings-runtime-value">{settings.data?.wechat.mode ?? "-"}</div>
                <p className="field-help">{t("settings.wechatModeHint")}</p>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.wechatStatus")}</label>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  <span
                    className={`status-badge ${
                      settings.data?.runtime.wechat.status === "ready" ? "stable" : "degraded"
                    }`}
                  >
                    {settings.data?.runtime.wechat.status ?? "-"}
                  </span>
                  <p className="field-help">{t("settings.wechatStatusHint")}</p>
                </div>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.wechatStatePath")}</label>
                <div className="settings-runtime-value">{settings.data?.wechat.state_path ?? "-"}</div>
                <p className="field-help">{t("settings.wechatStatePathHint")}</p>
              </div>
              <div className="field-card">
                <label className="field-label">{t("settings.wechatLoginCommand")}</label>
                <div className="settings-runtime-value">python -m src.channels.adapters.wechat_login</div>
                <p className="field-help">{t("settings.wechatLoginHint")}</p>
              </div>
            </div>
          </section>

          <section className="surface-panel settings-section" id="inference">
            <SettingsSectionHeader icon="rocket" title={t("settings.inference")} description={t("settings.inferenceHint")} />
            <div className="settings-grid">
              <div className="field-card">
                <label className="field-label">{t("settings.modelMaxRetries")}</label>
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={10}
                  value={maxRetries}
                  onChange={(event) => setMaxRetries(Number(event.target.value))}
                />
                <p className="field-help">{t("settings.maxRetriesHint")}</p>
              </div>
            </div>
          </section>

          <section className="surface-panel settings-section" id="secrets">
            <SettingsSectionHeader icon="settings" title={t("settings.secrets")} description={t("settings.secretsHint")} />
            <div className="settings-footer-actions" style={{ marginBottom: "var(--space-4)" }}>
              <button
                className="btn secondary"
                type="button"
                disabled={revealSecrets.isPending}
                onClick={() => {
                  if (showSecretValues) {
                    setShowSecretValues(false);
                    setRevealedSecrets([]);
                    return;
                  }
                  revealSecrets.mutate();
                }}
              >
                {showSecretValues ? t("settings.hideSecrets") : t("settings.showSecrets")}
              </button>
            </div>
            <div className="settings-secret-list">
              {secrets.map((secret) => (
                <div className="settings-secret-row" key={secret.label}>
                  <div>
                    <strong>{secret.label}</strong>
                    <p>
                      {showSecretValues
                        ? (secretValues[secret.envName]?.value || t("settings.secretMissing"))
                        : t("settings.envManaged", { env: secret.envName })}
                    </p>
                  </div>
                  <span className={`status-badge ${secretValues[secret.envName]?.is_set ? "stable" : "degraded"}`}>
                    {showSecretValues
                      ? secretValues[secret.envName]?.is_set
                        ? t("settings.secretVisible")
                        : t("settings.secretMissingBadge")
                      : t("settings.readOnlySecrets")}
                  </span>
                </div>
              ))}
            </div>
          </section>

          {(settings.data?.restart_required || saveError || applyError || restartPending) ? (
            <section className="surface-panel settings-section" id="restart">
              <SettingsSectionHeader
                icon="shield"
                title={t("settings.restartTitle")}
                description={t("settings.restartHint")}
              />
              <div className="settings-grid">
                {settings.data?.restart_required ? (
                  <div className="field-card">
                    <label className="field-label">{t("settings.restartRequiredLabel")}</label>
                    <div className="settings-runtime-value">
                      {restartPending ? t("settings.restartingValue") : t("settings.restartRequiredValue")}
                    </div>
                    <p className="field-help">
                      {restartReasons.length > 0 ? restartReasons.join(" / ") : t("settings.restartDefaultReason")}
                    </p>
                    <button
                      className="btn"
                      type="button"
                      disabled={applySavedSettings.isPending || restartPending}
                      onClick={() => applySavedSettings.mutate()}
                    >
                      {applySavedSettings.isPending || restartPending
                        ? t("settings.restartingButton")
                        : t("settings.applySavedNow")}
                    </button>
                  </div>
                ) : null}
                {saveError ? (
                  <div className="field-card">
                    <label className="field-label">{t("settings.saveErrorTitle")}</label>
                    <div className="settings-runtime-value">{t("settings.saveErrorValue")}</div>
                    <p className="field-help">{saveError}</p>
                  </div>
                ) : null}
                {applyError ? (
                  <div className="field-card">
                    <label className="field-label">{t("settings.applyErrorTitle")}</label>
                    <div className="settings-runtime-value">{t("settings.applyErrorValue")}</div>
                    <p className="field-help">{applyError}</p>
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}
        </div>
      </div>

      <footer className="settings-footer surface-panel">
        <div className="settings-footer-status">
          <Icon name="shield" className="icon-sm" />
          <span>{statusText}</span>
        </div>
        <div className="settings-footer-actions">
          <button
            className="btn ghost"
            type="button"
            onClick={() => {
              if (settings.data) {
                syncDraft(settings.data, {
                  setEnabled,
                  setMode,
                  setStreaming,
                  setMaxRetries,
                });
              }
            }}
          >
            {t("settings.discard")}
          </button>
          <button
            className="btn"
            type="button"
            disabled={!isDirty || update.isPending}
            onClick={() => update.mutate()}
          >
            {t("settings.apply")}
          </button>
        </div>
      </footer>
    </div>
  );
}
