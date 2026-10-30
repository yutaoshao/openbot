export type DemoMessage = { id: string; role: "user" | "assistant"; content: string };
export type DemoConversation = { id: string; title: string; platform: string };
export type DemoDetail = { conversation: DemoConversation; messages: DemoMessage[] };
export type DemoScenario = "ready" | "empty" | "starting" | "offline" | "error" | "long";
export type DemoPhase = "idle" | "tool" | "streaming" | "stopping";
