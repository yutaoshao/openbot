import { useState } from "react";
import { useI18n } from "../i18n";
import { ChoiceField, NumberField, ServiceGroup, ServiceToggle, TextField } from "./ServiceFields";
import type { ServicesConfiguration } from "./service-types";

export function ChannelServices({ value, onChange }: {
  value: ServicesConfiguration; onChange: (value: ServicesConfiguration) => void;
}) {
  const { t } = useI18n();
  const [allowedIds, setAllowedIds] = useState(value.telegram.allowed_user_ids.join(", "));
  const telegram = value.telegram;
  const feishu = value.feishu;
  const wechat = value.wechat;
  return <>
    <ServiceGroup title="Telegram" hint={t("desktopServices.telegramHint")}>
      <ServiceToggle label={t("settings.telegramEnabled")} checked={telegram.enabled}
        onChange={(enabled) => onChange({ ...value, telegram: { ...telegram, enabled } })} />
      <ChoiceField label={t("settings.telegramMode")} value={telegram.mode} choices={[["polling", "Polling"], ["webhook", "Webhook"]]}
        onChange={(mode) => onChange({ ...value, telegram: { ...telegram, mode } })} />
      <label className="desktop-service-field"><span className="field-label">{t("desktopServices.allowedUsers")}</span>
        <input className="input" value={allowedIds} pattern="[0-9,， ]*" onChange={(e) => {
          const next = e.target.value;
          setAllowedIds(next);
          const ids = next.split(/[,，]/).map((s) => s.trim()).filter(Boolean).map(Number);
          const valid = ids.every((id) => Number.isSafeInteger(id) && id > 0);
          e.target.setCustomValidity(valid ? "" : t("desktopServices.invalidUserIds"));
          if (valid) onChange({ ...value, telegram: { ...telegram, allowed_user_ids: ids } });
        }} />
        <span className="field-help">{t("desktopServices.allowedUsersHint")}</span>
      </label>
      <ServiceToggle label={t("settings.enableStreaming")} checked={telegram.enable_streaming}
        onChange={(enable_streaming) => onChange({ ...value, telegram: { ...telegram, enable_streaming } })} />
      <NumberField label={t("desktopServices.streamThrottle")} value={telegram.stream_throttle} min={0.1} step="any"
        onChange={(stream_throttle) => onChange({ ...value, telegram: { ...telegram, stream_throttle: stream_throttle! } })} />
      {telegram.mode === "webhook" && <TextField label={t("desktopServices.webhookUrl")} value={telegram.webhook_url} type="url" required={telegram.enabled}
        onChange={(webhook_url) => onChange({ ...value, telegram: { ...telegram, webhook_url: webhook_url || null } })} />}
    </ServiceGroup>
    <ServiceGroup title={t("desktopServices.feishu")} hint={t("desktopServices.feishuHint")}>
      <ServiceToggle label={t("desktopServices.feishuEnabled")} checked={feishu.enabled}
        onChange={(enabled) => onChange({ ...value, feishu: { ...feishu, enabled } })} />
      <ChoiceField label={t("settings.feishuMode")} value={feishu.mode} choices={[["long_connection", t("desktopServices.longConnection")], ["webhook", "Webhook"]]}
        onChange={(mode) => onChange({ ...value, feishu: { ...feishu, mode } })} />
    </ServiceGroup>
    <ServiceGroup title={t("desktopServices.wechat")} hint={t("desktopServices.wechatHint")}>
      <ServiceToggle label={t("desktopServices.wechatEnabled")} checked={wechat.enabled}
        onChange={(enabled) => onChange({ ...value, wechat: { ...wechat, enabled } })} />
      <TextField label={t("desktopLive.baseUrl")} value={wechat.api_base_url} type="url" required
        onChange={(api_base_url) => onChange({ ...value, wechat: { ...wechat, api_base_url } })} />
      <NumberField label={t("desktopServices.pollInterval")} value={wechat.poll_interval} min={0.1} step="any"
        onChange={(poll_interval) => onChange({ ...value, wechat: { ...wechat, poll_interval: poll_interval! } })} />
      <NumberField label={t("desktopServices.maxBackoff")} value={wechat.max_backoff} min={0.1} step="any"
        onChange={(max_backoff) => onChange({ ...value, wechat: { ...wechat, max_backoff: max_backoff! } })} />
    </ServiceGroup>
  </>;
}

export function RetrievalServices({ value, onChange }: {
  value: ServicesConfiguration; onChange: (value: ServicesConfiguration) => void;
}) {
  const { t } = useI18n();
  const embedding = value.embedding;
  const reranker = value.reranker;
  return <>
    <ServiceGroup title={t("settings.embedding")}>
      <ServiceToggle label={t("desktopServices.embeddingEnabled")} checked={embedding.enabled}
        onChange={(enabled) => onChange({ ...value, embedding: { ...embedding, enabled } })} />
      <ChoiceField label={t("desktopLive.provider")} value={embedding.provider} choices={[["openai_compatible", "OpenAI Compatible"], ["dashscope", "DashScope"]]}
        onChange={(provider) => onChange({ ...value, embedding: { ...embedding, provider } })} />
      <TextField label={t("desktopLive.modelName")} value={embedding.model} onChange={(model) => onChange({ ...value, embedding: { ...embedding, model } })} required />
      <TextField label={t("desktopLive.baseUrl")} value={embedding.base_url} type="url" onChange={(base_url) => onChange({ ...value, embedding: { ...embedding, base_url: base_url || null } })} />
      <NumberField label={t("desktopServices.dimensions")} value={embedding.dimensions} min={1} onChange={(dimensions) => onChange({ ...value, embedding: { ...embedding, dimensions: dimensions! } })} />
    </ServiceGroup>
    <ServiceGroup title={t("settings.reranker")}>
      <ServiceToggle label={t("desktopServices.rerankerEnabled")} checked={reranker.enabled}
        onChange={(enabled) => onChange({ ...value, reranker: { ...reranker, enabled } })} />
      <TextField label={t("desktopLive.modelName")} value={reranker.model} required onChange={(model) => onChange({ ...value, reranker: { ...reranker, model } })} />
      <TextField label={t("desktopLive.baseUrl")} value={reranker.base_url} type="url" required onChange={(base_url) => onChange({ ...value, reranker: { ...reranker, base_url } })} />
      <NumberField label={t("desktopServices.topN")} value={reranker.top_n} min={1} onChange={(top_n) => onChange({ ...value, reranker: { ...reranker, top_n: top_n! } })} />
    </ServiceGroup>
  </>;
}
