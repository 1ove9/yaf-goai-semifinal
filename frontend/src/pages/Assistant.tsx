import React, { useEffect, useRef, useState } from "react";
import { useI18n } from "../i18n";

interface ToolEvent {
  name: string;
  status: "running" | "ok" | "error";
  error?: string;
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  tools?: ToolEvent[];
}

/**
 * Assistant — agentic AI page backed by the /api/v1/chat endpoint
 * (server-side DeepSeek proxy with real-solver tools, streamed as SSE
 * data frames: {delta}, {tool}, {done}, {error}).
 */
const Assistant: React.FC = () => {
  const { t } = useI18n();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const appendToLast = (text: string) => {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant") {
        next[next.length - 1] = { ...last, content: last.content + text };
      }
      return next;
    });
  };

  const pushToolEvent = (evt: ToolEvent) => {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role !== "assistant") return prev;
      const tools = [...(last.tools ?? [])];
      if (evt.status === "running") {
        tools.push(evt);
      } else {
        // resolve the most recent still-running entry for this tool
        for (let i = tools.length - 1; i >= 0; i--) {
          if (tools[i].name === evt.name && tools[i].status === "running") {
            tools[i] = evt;
            break;
          }
        }
      }
      next[next.length - 1] = { ...last, tools };
      return next;
    });
  };

  const send = async () => {
    const question = input.trim();
    if (!question || streaming) return;

    // history for the server: text only (tool traces are display state)
    const history = [
      ...messages.map((m) => ({ role: m.role, content: m.content })),
      { role: "user" as const, content: question },
    ];
    setMessages([
      ...messages,
      { role: "user", content: question },
      { role: "assistant", content: "" },
    ]);
    setInput("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const resp = await fetch("/api/v1/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
        signal: controller.signal,
      });
      if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try {
          const j = (await resp.json()) as { detail?: string };
          if (j.detail) detail = j.detail;
        } catch {
          /* non-JSON error body */
        }
        appendToLast(`⚠ ${t("chatError")}: ${detail}`);
        return;
      }

      const reader = resp.body?.getReader();
      if (!reader) throw new Error("No response stream");
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          try {
            const evt = JSON.parse(line.slice(5)) as {
              delta?: string;
              tool?: ToolEvent;
              error?: string;
              done?: boolean;
            };
            if (evt.delta) appendToLast(evt.delta);
            if (evt.tool) pushToolEvent(evt.tool);
            if (evt.error) appendToLast(`⚠ ${t("chatError")}: ${evt.error}`);
          } catch {
            /* incomplete frame — ignored */
          }
        }
      }
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        appendToLast(`⚠ ${t("chatError")}: ${e instanceof Error ? e.message : String(e)}`);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const stop = () => abortRef.current?.abort();

  const clear = () => {
    stop();
    setMessages([]);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  };

  const lastIsEmptyAssistant =
    streaming && messages[messages.length - 1]?.role === "assistant" &&
    messages[messages.length - 1]?.content === "";

  return (
    <div className="chat-page panel">
      <div className="panel-head" style={{ justifyContent: "space-between" }}>
        <div>
          <h2 className="panel-title">{t("chatTitle")}</h2>
          <div className="chat-subtitle">{t("chatSubtitle")}</div>
        </div>
        {messages.length > 0 && (
          <button className="chat-clear" onClick={clear}>
            {t("chatClear")}
          </button>
        )}
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 ? (
          <div className="empty-state" style={{ height: "100%" }}>
            <span className="glyph">✳</span>
            {t("chatEmpty")}
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`chat-msg ${m.role}`}>
              <div className="chat-msg-role">{m.role === "user" ? t("chatYou") : t("chatAI")}</div>
              {m.tools && m.tools.length > 0 && (
                <div className="chat-tools">
                  {m.tools.map((tool, j) => (
                    <div key={j} className={`chat-tool ${tool.status}`}>
                      {tool.status === "running"
                        ? `⚙ ${t("chatToolRunning")} ${tool.name}…`
                        : tool.status === "ok"
                          ? `✓ ${tool.name} ${t("chatToolDone")}`
                          : `✗ ${tool.name} ${t("chatToolFailed")}${tool.error ? `: ${tool.error}` : ""}`}
                    </div>
                  ))}
                </div>
              )}
              <div className="chat-msg-body">
                {m.content || (lastIsEmptyAssistant && i === messages.length - 1 && !m.tools?.length ? (
                  <span className="chat-thinking">{t("chatThinking")}</span>
                ) : null)}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="chat-input-row">
        <textarea
          className="chat-input"
          rows={2}
          value={input}
          placeholder={t("chatPlaceholder")}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
        />
        {streaming ? (
          <button className="btn-primary chat-send" onClick={stop}>
            ■ {t("chatStop")}
          </button>
        ) : (
          <button className="btn-primary chat-send" onClick={() => void send()} disabled={!input.trim()}>
            ↥ {t("chatSend")}
          </button>
        )}
      </div>
    </div>
  );
};

export default Assistant;
