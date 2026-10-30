export type ModelEndpoint = {
  provider: "openai_compatible" | "openai_responses" | "anthropic";
  model: string;
  base_url: string | null;
  max_tokens: number;
  context_window: number | null;
  temperature: number;
  api_key_env: string;
  pricing_input: number | null;
  pricing_output: number | null;
  connect_timeout: number;
  read_timeout: number;
  reasoning_effort: "low" | "medium" | "high" | "xhigh";
  verbosity: "low" | "medium" | "high";
};

export type ServicesConfiguration = {
  model: {
    primary: ModelEndpoint;
    fallback: ModelEndpoint | null;
    max_retries: number;
    retry_base_delay: number;
    routing: {
      enabled: boolean;
      default_tier: "simple" | "complex";
      tiers: Partial<Record<"simple" | "complex", ModelEndpoint>>;
      rules: {
        simple_max_chars: number;
        complex_min_chars: number;
        tool_count_complex_threshold: number;
        simple_keywords: string[];
        complex_keywords: string[];
      };
    };
  };
  telegram: {
    enabled: boolean;
    mode: "polling" | "webhook";
    bot_token_env: string;
    webhook_url: string | null;
    webhook_secret: string | null;
    allowed_user_ids: number[];
    stream_throttle: number;
    enable_streaming: boolean;
  };
  feishu: {
    enabled: boolean;
    mode: "webhook" | "long_connection";
    app_id_env: string;
    app_secret_env: string;
    verification_token_env: string;
    encrypt_key_env: string;
  };
  wechat: {
    enabled: boolean;
    mode: "ilink_polling";
    state_path: string;
    api_base_url: string;
    poll_interval: number;
    max_backoff: number;
  };
  embedding: {
    enabled: boolean;
    provider: "openai_compatible" | "dashscope";
    model: string;
    base_url: string | null;
    api_key_env: string;
    dimensions: number;
  };
  reranker: {
    enabled: boolean;
    model: string;
    base_url: string;
    api_key_env: string;
    top_n: number;
  };
};

export type ServicesSnapshot = {
  configuration: ServicesConfiguration;
  secrets: Array<{ key: string; is_set: boolean }>;
  wechat: { logged_in: boolean };
};

export type SecretDraft = {
  values: Record<string, string>;
  cleared: string[];
};

export const newModelEndpoint = (): ModelEndpoint => ({
  provider: "openai_compatible", model: "", base_url: "https://api.openai.com/v1",
  max_tokens: 4096, context_window: null, temperature: 0.7, api_key_env: "",
  pricing_input: null, pricing_output: null, connect_timeout: 30, read_timeout: 300,
  reasoning_effort: "medium", verbosity: "low",
});
