import React, { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icons";
import { useI18n } from "../i18n";
import { useDesignContext } from "../lib/designContext";

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

const AssistantAvatar: React.FC = () => (
  <span className="avatar" aria-hidden="true">
    <svg viewBox="0 0 32 32" className="size-4">
      <path
        d="M16 4v24M9 8.5c4.7 4.8 4.7 10.2 0 15M23 8.5c-4.7 4.8-4.7 10.2 0 15"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="2.2"
      />
      <circle cx="16" cy="16" r="2.6" fill="currentColor" />
    </svg>
  </span>
);

/**
 * Assistant — agentic AI page backed by the /api/v1/chat endpoint
 * (server-side DeepSeek proxy with real-solver tools, streamed as SSE
 * data frames: {delta}, {tool}, {done}, {error}).
 */
const Assistant: React.FC = () => {
  const { lang, t, tEn } = useI18n();
  const { designContext } = useDesignContext();
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
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className="glass flex min-h-[760px] min-w-0 flex-col">
        <header className="flex items-start justify-between gap-4 border-b border-white/10 px-5 py-4 sm:px-6">
          <div>
            <span className="eyebrow">{t("chatTitle")}</span>
            {lang === "zh" ? (
              <p className="mt-1 font-serif text-sm italic text-white/[0.52]">{tEn("chatTitle")}</p>
            ) : null}
          </div>
          {messages.length > 0 ? (
            <button type="button" className="btn-ghost" onClick={clear}>
              <Icon name="trash" size={14} />
              {t("chatClear")}
            </button>
          ) : null}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-6" ref={scrollRef} aria-live="polite">
          {messages.length === 0 ? (
            <div className="grid h-full min-h-[360px] place-items-center text-center">
              <div className="max-w-lg">
                <AssistantAvatar />
                <h2 className="mt-4 text-xl font-semibold tracking-[-0.02em] text-[#ededf0]">{t("chatEmptyTitle")}</h2>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-white/[0.68]">{t("chatEmpty")}</p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {(["suggestionOne", "suggestionTwo", "suggestionThree"] as const).map((key) => (
                    <button key={key} type="button" className="sug" onClick={() => setInput(t(key))}>
                      {t(key)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((message, index) => {
                const isUser = message.role === "user";
                return (
                  <article key={index} className={`flex gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
                    {isUser ? (
                      <span className="grid size-8 flex-none place-items-center rounded-[12px] border border-white/10 bg-white/[0.07] text-xs font-semibold text-white/[0.82]">
                        {t("chatYou").slice(0, 1)}
                      </span>
                    ) : <AssistantAvatar />}
                    <div className={`min-w-0 max-w-[82%] ${isUser ? "text-right" : ""}`}>
                      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-white/[0.44]">
                        {isUser ? t("chatYou") : t("chatAI")}
                      </span>
                      {message.tools && message.tools.length > 0 ? (
                        <div className={`mt-2 flex flex-wrap gap-2 ${isUser ? "justify-end" : ""}`}>
                          {message.tools.map((tool, toolIndex) => {
                            const toolClass = tool.status === "running" ? "run" : tool.status;
                            return (
                              <span key={toolIndex} className={`tool ${toolClass}`}>
                                <Icon
                                  name={tool.status === "running" ? "refresh" : tool.status === "ok" ? "check" : "circle-stop"}
                                  size={13}
                                  className={tool.status === "running" ? "animate-spin motion-reduce:animate-none" : ""}
                                />
                                <span>
                                  {tool.name} · {tool.status === "running"
                                    ? t("chatToolRunning")
                                    : tool.status === "ok"
                                      ? t("chatToolDone")
                                      : t("chatToolFailed")}
                                  {tool.error ? ` · ${tool.error}` : ""}
                                </span>
                              </span>
                            );
                          })}
                        </div>
                      ) : null}
                      <div className={`mt-2 rounded-[18px] border px-4 py-3 text-left text-[14.5px] leading-7 ${
                        isUser
                          ? "border-white/10 bg-white/[0.08] text-white/[0.88]"
                          : "border-[rgba(169,196,232,.18)] bg-[rgba(169,196,232,.07)] text-white/[0.82]"
                      }`}>
                        <p className="whitespace-pre-wrap">
                          {message.content || (lastIsEmptyAssistant && index === messages.length - 1 && !message.tools?.length ? (
                            <span className="inline-flex items-center gap-2 text-white/[0.52]">
                              <Icon name="refresh" size={14} className="animate-spin motion-reduce:animate-none" />
                              {t("chatThinking")}
                            </span>
                          ) : null)}
                        </p>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </div>

        <div className="border-t border-white/10 p-4 sm:p-5">
          <div className="glass flex items-end gap-3 rounded-[18px] p-2">
            <textarea
              className="min-h-[54px] min-w-0 flex-1 resize-none bg-transparent px-2 py-2 text-sm leading-6 text-[#ededf0] outline-none placeholder:text-white/[0.44]"
              rows={2}
              value={input}
              aria-label={t("chatPlaceholder")}
              placeholder={t("chatPlaceholder")}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onKeyDown}
            />
            {streaming ? (
              <button type="button" className="btn-secondary border-[rgba(227,154,154,.42)] text-[#e39a9a]" onClick={stop}>
                <Icon name="circle-stop" size={15} />
                {t("chatStop")}
              </button>
            ) : (
              <button type="button" className="btn-primary" onClick={() => void send()} disabled={!input.trim()}>
                <Icon name="send" size={15} />
                {t("chatSend")}
              </button>
            )}
          </div>
          <p className="mt-3 text-center text-[11px] leading-5 text-white/[0.44]">{t("chatDisclaimer")}</p>
        </div>
      </section>

      <aside className="flex flex-col gap-4">
        <section className="glass p-[18px]">
          <div className="flex items-start justify-between gap-3">
            <span className="eyebrow">{t("designContextTitle")}</span>
            {designContext ? (
              <span className="chip gold">Analytical</span>
            ) : null}
          </div>
          {designContext ? (
            <dl className="mt-5 divide-y divide-white/[0.08] text-xs">
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("designName")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{designContext.designName}</dd>
              </div>
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("dipoleLength")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{(designContext.dipoleLengthM * 1000).toFixed(1)} mm</dd>
              </div>
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("centerFreq")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{designContext.freqGhz.toFixed(2)} GHz</dd>
              </div>
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("resonance")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{designContext.resonanceGhz.toFixed(2)} GHz</dd>
              </div>
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("minS11")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{designContext.minS11Db.toFixed(2)} dB</dd>
              </div>
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("solver")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{designContext.solver}</dd>
              </div>
              <div className="flex items-start justify-between gap-4 py-2.5">
                <dt className="text-white/[0.52]">{t("solverEvidenceMode")}</dt>
                <dd className="text-right font-mono text-white/[0.82]">{designContext.solverMode ?? "Analytical"}</dd>
              </div>
              {designContext.solverAnchorMode ? (
                <div className="flex items-start justify-between gap-4 py-2.5">
                  <dt className="text-white/[0.52]">{t("latestSolverAnchor")}</dt>
                  <dd className="text-right font-mono text-white/[0.82]">{designContext.solverAnchorMode} · {t("solverAnchorBadge")}</dd>
                </div>
              ) : null}
            </dl>
          ) : (
            <p className="mt-4 text-sm leading-6 text-white/[0.68]">{t("noDesignContext")}</p>
          )}
          <p className="mt-4 border-t border-white/[0.08] pt-4 text-[11px] leading-5 text-white/[0.44]">{t("designContextNote")}</p>
          <p className="mt-2 text-[11px] leading-5 text-white/[0.44]">{t("designContextEvidenceNote")}</p>
        </section>

        <section className="glass p-[18px]">
          <span className="eyebrow">{t("assistantToolsTitle")}</span>
          <div className="mt-4 space-y-3">
            {([
              ["simulate_patch", "toolSimulatePatch"],
              ["simulate_dipole", "toolSimulateDipole"],
              ["run_inverse_design", "toolInverseDesign"],
            ] as const).map(([name, descriptionKey]) => (
              <div key={name} className="card p-3.5">
                <div className="font-mono text-[11px] text-[#d6e2f2]">{name}</div>
                <p className="mt-1.5 text-[11px] leading-5 text-white/[0.52]">{t(descriptionKey)}</p>
              </div>
            ))}
          </div>
          <p className="mt-4 border-t border-white/[0.08] pt-4 text-[11px] leading-5 text-white/[0.44]">{t("footerHonesty")}</p>
        </section>
      </aside>
    </div>
  );
};

export default Assistant;
