import { api } from "../lib/api";
import type { ConversationDetail } from "./types";
import type { ChatMessage } from "../components/desktop/chat-view";

export const HISTORY_PAGE_SIZE = 200;
export type HistoryPage = ConversationDetail & { offset: number; missing?: boolean };
export type HistoryPageParam = { offset: number; limit: number };

export function earlierHistoryPage(page: HistoryPage): HistoryPageParam | undefined {
  if (page.offset <= 0) return undefined;
  const limit = Math.min(HISTORY_PAGE_SIZE, page.offset);
  return { offset: page.offset - limit, limit };
}

export function historyMessages(rows: ConversationDetail["messages"]): ChatMessage[] {
  return rows.flatMap((message) => {
    if (message.role !== "user" && message.role !== "assistant") return [];
    const reason = message.metadata?.turn_failure?.reason;
    const outcome = reason ? reason === "cancelled" ? "cancelled" : "failed" : undefined;
    const item: ChatMessage = { id: message.id, role: message.role, content: message.content, outcome };
    return [item];
  });
}

/** The server returns ascending messages; fetch the latest window first. */
export async function loadHistoryPage(id: string, page: HistoryPageParam | null): Promise<HistoryPage> {
  const path = `/api/conversations/${encodeURIComponent(id)}`;
  if (page !== null) {
    return { ...await api.get<ConversationDetail>(`${path}?limit=${page.limit}&offset=${page.offset}`), offset: page.offset };
  }
  const first = await api.get<ConversationDetail>(`${path}?limit=${HISTORY_PAGE_SIZE}&offset=0`);
  const latestOffset = Math.max(0, first.conversation.message_count - HISTORY_PAGE_SIZE);
  if (!latestOffset) return { ...first, offset: 0 };
  return { ...await api.get<ConversationDetail>(`${path}?limit=${HISTORY_PAGE_SIZE}&offset=${latestOffset}`), offset: latestOffset };
}
