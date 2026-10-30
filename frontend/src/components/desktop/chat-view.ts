export type ChatMessage = { id: string; role: "user" | "assistant"; content: string; outcome?: "cancelled" | "failed" };
export type ChatPhase = "idle" | "queued" | "tool" | "streaming" | "stopping";
export type ChatScenario = "ready" | "empty" | "starting" | "offline" | "error" | "long";

/** Presentation contract shared by the synthetic preview and the live desktop. */
export type ChatViewModel = {
  selectedId: string | null;
  title: string;
  scenario: ChatScenario;
  phase: ChatPhase;
  phaseLabel?: string;
  messages: ChatMessage[];
  pendingInput: string;
  output: string;
  toolDetail?: string;
  busy: boolean;
  loading: boolean;
  error: boolean;
  stopped: boolean;
  stoppedDetail?: string;
  failure: string | null;
  selectConversation: (id: string | null) => void;
  submit: (text: string) => void | Promise<void>;
  stop: () => void;
  reconnect?: () => void;
  recover?: () => void | Promise<void>;
  withdraw?: () => void | Promise<void>;
  withdrawing?: boolean;
  hasEarlier?: boolean;
  loadingEarlier?: boolean;
  loadEarlier?: () => void | Promise<unknown>;
  reloadHistory?: () => void | Promise<unknown>;
};
