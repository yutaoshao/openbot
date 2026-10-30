import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import { historyMessages, loadHistoryPage } from "./history";

vi.mock("../lib/api", () => ({ api: { get: vi.fn() } }));
beforeEach(() => vi.mocked(api.get).mockReset());

describe("desktop history paging", () => {
  it("preserves stopped and failed outcomes instead of presenting partial replies as complete", () => {
    expect(historyMessages([
      { id: "a", role: "assistant", content: "Partial", metadata: { turn_failure: { reason: "cancelled" } } },
      { id: "b", role: "assistant", content: "Failed", metadata: { turn_failure: { reason: "execution_error" } } },
      { id: "c", role: "tool", content: "Not a chat bubble" },
    ])).toEqual([
      { id: "a", role: "assistant", content: "Partial", outcome: "cancelled" },
      { id: "b", role: "assistant", content: "Failed", outcome: "failed" },
    ]);
  });
  it("opens the latest 200 messages rather than the earliest window", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ conversation: { message_count: 650 }, messages: [{ id: "old" }] })
      .mockResolvedValueOnce({ conversation: { message_count: 650 }, messages: [{ id: "latest" }] });
    const page = await loadHistoryPage("web/a", null);
    expect(page.offset).toBe(450);
    expect(page.messages).toEqual([{ id: "latest" }]);
    expect(api.get).toHaveBeenNthCalledWith(2, "/api/conversations/web%2Fa?limit=200&offset=450");
  });

  it("loads an earlier explicit page without refetching the first window", async () => {
    vi.mocked(api.get).mockResolvedValue({ conversation: { message_count: 650 }, messages: [] });
    expect((await loadHistoryPage("a", { offset: 250, limit: 200 })).offset).toBe(250);
    expect(api.get).toHaveBeenCalledOnce();
    expect(api.get).toHaveBeenCalledWith("/api/conversations/a?limit=200&offset=250");
  });
});
