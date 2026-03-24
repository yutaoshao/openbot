import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { api, wsBaseUrl } from "../lib/api";

type StreamEvent = {
  type?: string;
  conversation_id?: string;
  chunk_type?: "text" | "tool_status" | "done";
  text?: string;
  tool_name?: string;
};

type ChatItem = {
  id: string;
  prompt: string;
  reply: string;
  attachments: string[];
};

export function ChatBar(): JSX.Element {
  const [message, setMessage] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [preview, setPreview] = useState("");
  const [status, setStatus] = useState("idle");
  const [expanded, setExpanded] = useState(false);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [history, setHistory] = useState<ChatItem[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const previewRef = useRef("");
  const pendingResolveRef = useRef<(() => void) | null>(null);

  const wsUrl = useMemo(() => `${wsBaseUrl()}/api/ws/chat`, []);

  useEffect(() => {
    return () => {
      socketRef.current?.close();
    };
  }, []);

  useEffect(() => {
    previewRef.current = preview;
  }, [preview]);

  const ensureSocket = async (): Promise<WebSocket> => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      return socketRef.current;
    }

    const ws = new WebSocket(wsUrl);
    socketRef.current = ws;

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("WebSocket connect failed"));
    });

    ws.onmessage = (event) => {
      const payload = JSON.parse(event.data) as StreamEvent;
      if (payload.type === "connected" && payload.conversation_id) {
        setConversationId(payload.conversation_id);
        return;
      }

      if (payload.chunk_type === "text") {
        setPreview((prev) => prev + (payload.text || ""));
      }
      if (payload.chunk_type === "tool_status") {
        setStatus(`Tool: ${payload.tool_name}`);
      }
      if (payload.chunk_type === "done") {
        setStatus("done");
        pendingResolveRef.current?.();
        pendingResolveRef.current = null;
      }
    };

    return ws;
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;

    const attachmentSuffix = attachments.length
      ? `\n\nAttached files:\n${attachments.map((name) => `- ${name}`).join("\n")}`
      : "";
    const merged = `${text}${attachmentSuffix}`;

    setStatus("sending");
    setPreview("");
    setMessage("");

    try {
      const ws = await ensureSocket();
      await new Promise<void>((resolve) => {
        pendingResolveRef.current = resolve;
        ws.send(JSON.stringify({ message: merged, conversation_id: conversationId }));
      });
      setHistory((prev) => [
        {
          id: crypto.randomUUID(),
          prompt: text,
          reply: previewRef.current,
          attachments,
        },
        ...prev,
      ]);
    } catch {
      const body = await api.post<{ reply: string; conversation_id: string }>("/api/chat", {
        message: merged,
        conversation_id: conversationId,
        platform: "web",
      });
      setConversationId(body.conversation_id);
      setPreview(body.reply);
      setStatus("done (fallback)");
      setHistory((prev) => [
        {
          id: crypto.randomUUID(),
          prompt: text,
          reply: body.reply,
          attachments,
        },
        ...prev,
      ]);
    } finally {
      setAttachments([]);
    }
  };

  return (
    <div className="chatbar">
      <form onSubmit={submit}>
        <input
          className="input"
          placeholder="Ask OpenBot..."
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
        <button className="btn" type="submit">
          Send
        </button>
      </form>
      <div className="chatbar-meta">
        <span className="mono">{status}</span>
        {preview ? <span style={{ marginLeft: 4 }}>{preview.slice(0, 220)}</span> : null}
      </div>
      <div className="chatbar-actions">
        <input
          type="file"
          multiple
          onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            setAttachments(files.map((file) => file.name));
          }}
        />
        {attachments.length ? <span className="mono" style={{ color: "var(--text-muted)" }}>{attachments.join(", ")}</span> : null}
        <button className="btn secondary" type="button" onClick={() => setExpanded((prev) => !prev)}>
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>
      {expanded ? (
        <section className="card" style={{ maxWidth: 1100, margin: "var(--space-3) auto 0" }}>
          <h3>Chat History</h3>
          <div style={{ whiteSpace: "pre-wrap" }} className="mono">
            {preview || "(empty)"}
          </div>
          <div style={{ maxHeight: 260, overflow: "auto", marginTop: "var(--space-2)" }}>
            {history.map((item) => (
              <div key={item.id} style={{ borderTop: "1px solid var(--border-soft)", paddingTop: "var(--space-2)", marginTop: "var(--space-2)" }}>
                <p style={{ color: "var(--text-muted)", margin: "0 0 4px" }}>
                  <strong style={{ color: "var(--text)", fontSize: 14 }}>Q:</strong> {item.prompt}
                </p>
                {item.attachments.length ? <p className="mono" style={{ color: "var(--text-dim)", margin: "0 0 4px" }}>{item.attachments.join(", ")}</p> : null}
                <p style={{ margin: 0 }}>
                  <strong style={{ color: "var(--text)", fontSize: 14 }}>A:</strong> {item.reply || "(streaming...)"}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
