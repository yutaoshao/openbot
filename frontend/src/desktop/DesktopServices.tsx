import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../i18n";
import { api, type JsonValue } from "../lib/api";
import { useSettingsDraft } from "./SettingsDrafts";
import { ChannelServices, RetrievalServices } from "./ChannelServices";
import { ModelServices } from "./ModelServices";
import { SecretField, ServiceGroup } from "./ServiceFields";
import { WeChatLogin } from "./WeChatLogin";
import type { SecretDraft, ServicesSnapshot } from "./service-types";

const credentialLabels: ReadonlyArray<readonly [string, string]> = [
  ["model.primary", "desktopServices.secret.primary"], ["model.fallback", "desktopServices.secret.fallback"],
  ["model.routing.simple", "desktopServices.secret.simple"], ["model.routing.complex", "desktopServices.secret.complex"],
  ["telegram.bot_token", "desktopServices.secret.telegram"], ["telegram.webhook_secret", "desktopServices.secret.webhook"],
  ["feishu.app_id", "desktopServices.secret.feishuId"], ["feishu.app_secret", "desktopServices.secret.feishuSecret"],
  ["feishu.verification_token", "desktopServices.secret.feishuVerify"], ["feishu.encrypt_key", "desktopServices.secret.feishuEncrypt"],
  ["embedding.api_key", "desktopServices.secret.embedding"], ["reranker.api_key", "desktopServices.secret.reranker"],
  ["tavily.api_key", "desktopServices.secret.tavily"],
];

function ServicesEditor({ snapshot, busy }: { snapshot: ServicesSnapshot; busy: boolean }) {
  const { t } = useI18n();
  const cache = useQueryClient();
  const [configuration, setConfiguration] = useState(snapshot.configuration);
  const [saved, setSaved] = useState(snapshot.configuration);
  const [secrets, setSecrets] = useState<SecretDraft>({ values: {}, cleared: [] });
  const [restarting, setRestarting] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const save = useMutation({
    mutationFn: (submitted: { configuration: typeof configuration; secrets: SecretDraft }) => api.put<{ requires_restart: boolean }>("/api/desktop/services", {
      configuration: submitted.configuration as unknown as JsonValue,
      secrets: Object.fromEntries(Object.entries(submitted.secrets.values).filter(([, value]) => value.trim())),
      clear_secrets: submitted.secrets.cleared,
    }),
    onSuccess: (result, submitted) => {
      setSaved(submitted.configuration);
      setSecrets({ values: {}, cleared: [] }); setRestarting(result.requires_restart);
      if (!result.requires_restart) void cache.invalidateQueries({ queryKey: ["desktop-services"] });
    },
  });
  const changed = JSON.stringify(configuration) !== JSON.stringify(saved)
    || secrets.cleared.length > 0 || Object.values(secrets.values).some((v) => v.trim());
  useSettingsDraft(Boolean(changed), save.isPending);
  return <form className="desktop-services-form" onInvalidCapture={(event) => {
    let container = (event.target as HTMLElement).closest("details");
    while (container) { container.open = true; container = container.parentElement?.closest("details") ?? null; }
    setInvalid(true);
  }} onInputCapture={() => setInvalid(false)} onSubmit={(event) => {
    event.preventDefault(); if (!save.isPending && !restarting && !busy && changed) save.mutate({ configuration, secrets });
  }}>
    <fieldset disabled={save.isPending || restarting} className="desktop-service-editor">
      <details className="desktop-settings-details" open>
        <summary>{t("desktopServices.channels")}</summary>
        <ChannelServices value={configuration} onChange={setConfiguration} />
      </details>
      <details className="desktop-settings-details">
        <summary>{t("desktopServices.models")}</summary>
        <ModelServices value={configuration.model} onChange={(model) => setConfiguration({ ...configuration, model })} />
      </details>
      <details className="desktop-settings-details">
        <summary>{t("desktopServices.retrieval")}</summary>
        <RetrievalServices value={configuration} onChange={setConfiguration} />
      </details>
      <details className="desktop-settings-details">
        <summary>{t("settings.secrets")}</summary>
        <ServiceGroup title={t("desktopServices.credentials")} hint={t("desktopServices.credentialsHint")}>
          {credentialLabels.map(([name, key]) => <SecretField key={name} name={name} label={t(key)} draft={secrets} onChange={setSecrets}
            saved={snapshot.secrets.some((item) => item.key === name && item.is_set)} />)}
        </ServiceGroup>
      </details>
    </fieldset>
    {busy && <p role="status">{t("desktopLive.busySettings")}</p>}
    {restarting && <p role="status">{t("desktopLive.restarting")}</p>}
    {save.isSuccess && !restarting && <p role="status">{t("desktopServices.demoSaved")}</p>}
    {save.error && <p role="alert">{save.error.message}</p>}
    {invalid && <p role="alert">{t("desktopServices.invalidFields")}</p>}
    <button className="btn" type="submit" disabled={busy || save.isPending || restarting || !changed}>{t("desktopLive.saveRestart")}</button>
  </form>;
}

export function DesktopServices({ busy, active = true }: { busy: boolean; active?: boolean }) {
  const { t } = useI18n();
  const query = useQuery({ queryKey: ["desktop-services"], queryFn: () => api.get<ServicesSnapshot>("/api/desktop/services"),
    enabled: active, staleTime: 0, retry: false });
  return <>
    <section className="surface-panel settings-section" id="services">
      <h2>{t("desktopServices.title")}</h2>
      <p className="field-help">{t("desktopServices.hint")}</p>
      {query.isPending && <p role="status">{t("common.loading")}</p>}
      {query.error && <p role="alert">{query.error.message} <button className="btn ghost" onClick={() => void query.refetch()}>{t("desktop.reconnect")}</button></p>}
      {query.data?.configuration && <ServicesEditor snapshot={query.data} busy={busy} />}
    </section>
    {active && query.data?.configuration && <WeChatLogin enabled={query.data.configuration.wechat.enabled} loggedIn={query.data.wechat.logged_in} />}
  </>;
}
