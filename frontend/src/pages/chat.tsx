import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { api, wsBaseUrl } from "../lib/api";
import { renderMarkdown } from "../lib/markdown";

type StreamEvent = {
  type?: string;
  conversation_id?: string;
  chunk_type?: "text" | "tool_status" | "done";
  text?: string;
  tool_name?: string;
};

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export function ChatPage(): JSX.Element {
  const [message, setMessage] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [status, setStatus] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const streamTextRef = useRef("");
  const pendingResolveRef = useRef<(() => void) | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const wsUrl = useMemo(() => `${wsBaseUrl()}/api/ws/chat`, []);

  useEffect(() => {
    return () => {
      socketRef.current?.close();
    };
  }, []);

  useEffect(() => {
    streamTextRef.current = streamText;
  }, [streamText]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamText]);

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

      // Non-streaming fallback: server sent a complete message
      if (payload.type === "message" && (payload as any).text) {
        setStreamText((payload as any).text);
        pendingResolveRef.current?.();
        pendingResolveRef.current = null;
        return;
      }

      if (payload.chunk_type === "text") {
        setStreamText((prev) => prev + (payload.text || ""));
      }
      if (payload.chunk_type === "tool_status") {
        setStatus(`Using tool: ${payload.tool_name}`);
      }
      if (payload.chunk_type === "done") {
        setStatus("");
        pendingResolveRef.current?.();
        pendingResolveRef.current = null;
      }
    };

    return ws;
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = message.trim();
    if (!text || streaming) return;

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setMessage("");
    setStreaming(true);
    setStreamText("");
    setStatus("");

    try {
      const ws = await ensureSocket();
      await new Promise<void>((resolve) => {
        pendingResolveRef.current = resolve;
        ws.send(JSON.stringify({ message: text, conversation_id: conversationId }));
      });
      const reply = streamTextRef.current;
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: reply },
      ]);
    } catch {
      const body = await api.post<{ reply: string; conversation_id: string }>("/api/chat", {
        message: text,
        conversation_id: conversationId,
        platform: "web",
      });
      setConversationId(body.conversation_id);
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "assistant", content: body.reply },
      ]);
    } finally {
      setStreaming(false);
      setStreamText("");
    }
  };

  const hasMessages = messages.length > 0;

  // Empty state: centered input
  if (!hasMessages && !streaming) {
    return (
      <div className="chat-container">
        <div className="chat-empty">
          <h2 className="chat-empty-title">OpenBot</h2>
          <p className="chat-empty-subtitle">Ask me anything</p>
          <form onSubmit={submit}>
            <input
              className="input"
              placeholder="Type your message..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              autoFocus
            />
            <button className="btn" type="submit" disabled={!message.trim()}>
              Send
            </button>
          </form>
        </div>
      </div>
    );
  }

  // Active state: messages list + bottom input
  return (
    <div className="chat-container">
      <div className="chat-messages">
        {messages.map((msg) => (
          <div className="chat-bubble" key={msg.id}>
            <div className="chat-bubble-role">{msg.role}</div>
            <div
              className="chat-bubble-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
            />
          </div>
        ))}
        {streaming && (
          <div className="chat-bubble">
            <div className="chat-bubble-role">assistant</div>
            <div className="chat-bubble-content">
              {streamText
                ? <span dangerouslySetInnerHTML={{ __html: renderMarkdown(streamText) }} />
                : <span className="chat-bubble-streaming">{status || "Thinking..."}</span>
              }
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-bar">
        <form onSubmit={submit}>
          <input
            className="input"
            placeholder="Type your message..."
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={streaming}
            autoFocus
          />
          <button className="btn" type="submit" disabled={streaming || !message.trim()}>
            Send
          </button>
        </form>
        {status ? <div className="chat-meta mono">{status}</div> : null}
      </div>
    </div>
  );
}
