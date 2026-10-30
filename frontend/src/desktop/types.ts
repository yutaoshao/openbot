export type DesktopStatus = {
  configured: boolean;
  work_dir: string;
  data_dir: string;
  model: {
    provider: "openai_compatible" | "openai_responses" | "anthropic";
    base_url: string;
    model: string;
    api_key_set: boolean;
  };
  permissions: { bash: boolean; code_executor: boolean };
  busy: boolean;
  import_result?: { status: "imported" | "failed_restored" | "unknown" } | null;
};

export type ChatRunStatus = "queued" | "running" | "stopping" | "completed" | "cancelled" | "failed";
export type ChatRun = {
  run_id: string;
  request_id?: string;
  conversation_id: string;
  status: ChatRunStatus;
  text: string;
  tool_events: Array<{ name: string; status: string; text?: string }>;
  error?: string | null;
};
export const terminalRun = (run: ChatRun): boolean => ["completed", "cancelled", "failed"].includes(run.status);

export type ConversationDetail = {
  conversation: { id: string; title: string | null; message_count: number };
  messages: Array<{ id: string; role: string; content: string; metadata?: { turn_failure?: { reason?: string } } | null }>;
};
