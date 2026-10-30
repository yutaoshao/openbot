import { useI18n } from "../i18n";
import { ChoiceField, KeywordsField, NumberField, ServiceGroup, ServiceToggle, TextField } from "./ServiceFields";
import { newModelEndpoint, type ModelEndpoint, type ServicesConfiguration } from "./service-types";

export function ModelFields({ value, onChange, advancedOnly = false }: {
  value: ModelEndpoint; onChange: (value: ModelEndpoint) => void; advancedOnly?: boolean;
}) {
  const { t } = useI18n();
  const update = <K extends keyof ModelEndpoint>(key: K, next: ModelEndpoint[K]) => onChange({ ...value, [key]: next });
  return <>
    {!advancedOnly && <>
      <ChoiceField label={t("desktopLive.provider")} value={value.provider} onChange={(v) => update("provider", v)} choices={[
        ["openai_compatible", "OpenAI Compatible"], ["openai_responses", "OpenAI Responses"], ["anthropic", "Anthropic"],
      ]} />
      <TextField label={t("desktopLive.modelName")} value={value.model} onChange={(v) => update("model", v)} required />
      <TextField label={t("desktopLive.baseUrl")} value={value.base_url} onChange={(v) => update("base_url", v || null)} type="url" />
    </>}
    <NumberField label={t("desktopServices.maxTokens")} value={value.max_tokens} min={1} onChange={(v) => update("max_tokens", v!)} />
    <NumberField label={t("desktopServices.contextWindow")} value={value.context_window} min={1} nullable onChange={(v) => update("context_window", v)} />
    <NumberField label={t("desktopServices.temperature")} value={value.temperature} step="any" onChange={(v) => update("temperature", v!)} />
    <NumberField label={t("desktopServices.connectTimeout")} value={value.connect_timeout} min={0.1} step="any" onChange={(v) => update("connect_timeout", v!)} />
    <NumberField label={t("desktopServices.readTimeout")} value={value.read_timeout} min={0.1} step="any" onChange={(v) => update("read_timeout", v!)} />
    <ChoiceField label={t("desktopServices.reasoning")} value={value.reasoning_effort} onChange={(v) => update("reasoning_effort", v)}
      choices={["low", "medium", "high", "xhigh"].map((v) => [v as ModelEndpoint["reasoning_effort"], v])} />
    <ChoiceField label={t("desktopServices.verbosity")} value={value.verbosity} onChange={(v) => update("verbosity", v)}
      choices={["low", "medium", "high"].map((v) => [v as ModelEndpoint["verbosity"], v])} />
    <NumberField label={t("desktopServices.pricingInput")} value={value.pricing_input} nullable step="any" onChange={(v) => update("pricing_input", v)} />
    <NumberField label={t("desktopServices.pricingOutput")} value={value.pricing_output} nullable step="any" onChange={(v) => update("pricing_output", v)} />
  </>;
}

export function ModelServices({ value, onChange }: {
  value: ServicesConfiguration["model"]; onChange: (value: ServicesConfiguration["model"]) => void;
}) {
  const { t } = useI18n();
  const routing = value.routing;
  return <>
    <ServiceGroup title={t("desktopServices.primaryAdvanced")}>
      <ModelFields value={value.primary} onChange={(primary) => onChange({ ...value, primary })} advancedOnly />
      <NumberField label={t("settings.modelMaxRetries")} value={value.max_retries} onChange={(v) => onChange({ ...value, max_retries: v! })} />
      <NumberField label={t("desktopServices.retryDelay")} value={value.retry_base_delay} step="any" onChange={(v) => onChange({ ...value, retry_base_delay: v! })} />
    </ServiceGroup>
    <ServiceGroup title={t("settings.fallback")}>
      <ServiceToggle label={t("desktopServices.useFallback")} checked={value.fallback !== null}
        onChange={(enabled) => onChange({ ...value, fallback: enabled ? newModelEndpoint() : null })} />
      {value.fallback && <ModelFields value={value.fallback} onChange={(fallback) => onChange({ ...value, fallback })} />}
    </ServiceGroup>
    <ServiceGroup title={t("desktopServices.routing")} hint={t("desktopServices.routingHint")}>
      <ServiceToggle label={t("desktopServices.routingEnabled")} checked={routing.enabled}
        onChange={(enabled) => onChange({ ...value, routing: { ...routing, enabled, tiers: enabled ? {
          simple: routing.tiers.simple ?? newModelEndpoint(), complex: routing.tiers.complex ?? newModelEndpoint(),
        } : routing.tiers } })} />
      {routing.enabled && <>
        <ChoiceField label={t("desktopServices.defaultTier")} value={routing.default_tier} choices={[["simple", t("desktopServices.simple")], ["complex", t("desktopServices.complex")]]}
          onChange={(default_tier) => onChange({ ...value, routing: { ...routing, default_tier } })} />
        {(["simple", "complex"] as const).map((tier) => <div className="desktop-wide-field" key={tier}>
          <ServiceGroup title={t(`desktopServices.${tier}`)}>
            <ModelFields value={routing.tiers[tier] ?? newModelEndpoint()} onChange={(endpoint) => onChange({ ...value, routing: { ...routing, tiers: { ...routing.tiers, [tier]: endpoint } } })} />
          </ServiceGroup>
        </div>)}
        {(["simple_max_chars", "complex_min_chars", "tool_count_complex_threshold"] as const).map((key) =>
          <NumberField key={key} label={t(`desktopServices.${key}`)} value={routing.rules[key]}
            onChange={(next) => onChange({ ...value, routing: { ...routing, rules: { ...routing.rules, [key]: next! } } })} />)}
        {(["simple_keywords", "complex_keywords"] as const).map((key) =>
          <KeywordsField key={key} label={t(`desktopServices.${key}`)} values={routing.rules[key]}
            onChange={(next) => onChange({ ...value, routing: { ...routing, rules: { ...routing.rules, [key]: next } } })} />)}
      </>}
    </ServiceGroup>
  </>;
}
