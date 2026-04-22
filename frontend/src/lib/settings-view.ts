type Settings = {
  api: { local_only: boolean };
  telegram: { enabled: boolean; enable_streaming: boolean; mode: string; bot_token_env: string };
  feishu: { enabled: boolean; mode: string; app_id_env: string; app_secret_env: string; verification_token_env: string; encrypt_key_env: string };
  wechat: { enabled: boolean; mode: string; state_path: string; api_base_url: string; poll_interval: number; max_backoff: number };
  embedding: { api_key_env: string };
  reranker: { api_key_env: string };
  runtime: {
    telegram: { enabled: boolean; mode: string | null; status: string; missing_env_vars: string[] };
    feishu: { enabled: boolean; mode: string | null; status: string; missing_env_vars: string[] };
    wechat: { enabled: boolean; mode: string | null; status: string; missing_env_vars: string[] };
  };
  model: {
    max_retries: number;
    primary: { model: string; api_key_env: string };
    fallback: { model: string; api_key_env: string } | null;
  };
  restart_required: boolean;
  restart_reasons: string[];
};

type SecretRow = {
  label: string;
  envName: string;
};

type SecretValue = {
  env_name: string;
  value: string;
  is_set: boolean;
};

type DraftSetters = {
  setEnabled: (value: boolean) => void;
  setMode: (value: string) => void;
  setStreaming: (value: boolean) => void;
  setMaxRetries: (value: number) => void;
};

export function syncDraft(settings: Settings, setters: DraftSetters): void {
  setters.setEnabled(settings.telegram.enabled);
  setters.setMode(settings.telegram.mode);
  setters.setStreaming(settings.telegram.enable_streaming);
  setters.setMaxRetries(settings.model.max_retries);
}

export function buildSecrets(settings: Settings, t: (key: string) => string): SecretRow[] {
  const rows: SecretRow[] = [
    { label: t("settings.primary"), envName: settings.model.primary.api_key_env },
    { label: t("settings.telegram"), envName: settings.telegram.bot_token_env },
  ];
  if (settings.model.fallback) {
    rows.splice(1, 0, { label: t("settings.fallback"), envName: settings.model.fallback.api_key_env });
  }
  rows.push(
    { label: "feishu_app_id", envName: settings.feishu.app_id_env },
    { label: "feishu_app_secret", envName: settings.feishu.app_secret_env },
    { label: "feishu_verification_token", envName: settings.feishu.verification_token_env },
    { label: "feishu_encrypt_key", envName: settings.feishu.encrypt_key_env },
    { label: t("settings.embedding"), envName: settings.embedding.api_key_env },
    { label: t("settings.reranker"), envName: settings.reranker.api_key_env },
  );
  return rows;
}

export function formatRestartReasons(
  settings: Settings,
  t: (key: string) => string,
): string[] {
  return settings.restart_reasons.map((reason) => t(`settings.restartReason.${reason}`));
}

export function secretValueMap(secrets: SecretValue[]): Record<string, SecretValue> {
  return Object.fromEntries(secrets.map((item) => [item.env_name, item]));
}

export type { Settings, SecretRow, SecretValue };
