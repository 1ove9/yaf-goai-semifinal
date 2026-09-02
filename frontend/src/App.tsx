import React, { useState } from "react";
import { Icon, IconName } from "./components/Icons";
import { MsgKey, useI18n } from "./i18n";
import { SocketProvider, useSocket } from "./lib/socket";

const DesignEditor = React.lazy(() => import("./pages/DesignEditor"));
const Discovery = React.lazy(() => import("./pages/Discovery"));
const Monitor = React.lazy(() => import("./pages/Monitor"));
const Assistant = React.lazy(() => import("./pages/Assistant"));

type Page = "discover" | "design" | "monitor" | "assistant";

interface PageMeta {
  icon: IconName;
  label: MsgKey;
  title: MsgKey;
  description: MsgKey;
}

const PAGE_META: Record<Page, PageMeta> = {
  discover: {
    icon: "layers",
    label: "navDiscover",
    title: "discoveryTitle",
    description: "discoveryDescription",
  },
  design: {
    icon: "cube",
    label: "navDesign",
    title: "designTitle",
    description: "designDescription",
  },
  monitor: {
    icon: "activity",
    label: "navMonitor",
    title: "monitorTitle",
    description: "monitorDescription",
  },
  assistant: {
    icon: "sparkles",
    label: "navAssistant",
    title: "assistantTitle",
    description: "assistantDescription",
  },
};

const BrandMark: React.FC = () => (
  <div className="relative grid size-9 place-items-center overflow-hidden rounded-xl border border-white/10 bg-white/[0.045] shadow-[0_0_30px_rgba(84,230,181,0.08)]">
    <svg viewBox="0 0 32 32" className="size-6 text-signal-400" aria-hidden="true">
      <path d="M16 4v24M9 8.5c4.7 4.8 4.7 10.2 0 15M23 8.5c-4.7 4.8-4.7 10.2 0 15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <circle cx="16" cy="16" r="2.4" fill="currentColor" />
    </svg>
    <span className="absolute right-1.5 top-1.5 size-1 rounded-full bg-signal-300 shadow-[0_0_8px_#8df5d0]" />
  </div>
);

const Shell: React.FC = () => {
  const [page, setPage] = useState<Page>("discover");
  const { lang, setLang, t } = useI18n();
  const { connected } = useSocket();
  const activeMeta = PAGE_META[page];

  const pageContent = page === "discover"
    ? <Discovery />
    : page === "design"
      ? <DesignEditor />
      : page === "monitor"
        ? <Monitor />
        : <Assistant />;

  return (
    <div className="min-h-screen bg-ink-950 text-warm-50">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-white/[0.065] bg-ink-900/95 px-4 py-5 backdrop-blur-xl lg:flex">
        <div className="flex items-center gap-3 px-2">
          <BrandMark />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[15px] font-semibold tracking-[-0.02em]">YAF</span>
              <span className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-white/35">alpha</span>
            </div>
            <p className="truncate text-[11px] text-white/38">Antenna Forge</p>
          </div>
        </div>

        <div className="mt-7 px-2">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/25">{t("workspace")}</p>
          <div className="flex w-full items-center gap-3 rounded-xl border border-white/[0.07] bg-white/[0.035] p-2.5">
            <span className="grid size-8 place-items-center rounded-lg bg-signal-400/10 text-signal-300">
              <Icon name="radio" size={16} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-white/85">{t("projectName")}</span>
              <span className="mt-0.5 block font-mono text-[9px] uppercase tracking-wider text-white/30">{t("projectType")}</span>
            </span>
          </div>
        </div>

        <nav className="mt-7 space-y-1" aria-label={t("primaryNavigation")}>
          {(Object.entries(PAGE_META) as [Page, PageMeta][]).map(([key, meta]) => {
            const active = page === key;
            return (
              <button
                key={key}
                onClick={() => setPage(key)}
                aria-current={active ? "page" : undefined}
                className={`group relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13px] transition-all ${
                  active
                    ? "bg-white/[0.065] text-white shadow-[inset_0_1px_rgba(255,255,255,0.04)]"
                    : "text-white/45 hover:bg-white/[0.035] hover:text-white/80"
                }`}
              >
                {active ? <span className="absolute -left-4 h-5 w-0.5 rounded-r-full bg-signal-400 shadow-[0_0_12px_rgba(84,230,181,0.7)]" /> : null}
                <Icon name={meta.icon} size={17} className={active ? "text-signal-300" : "text-white/35 group-hover:text-white/60"} />
                <span>{t(meta.label)}</span>
              </button>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3">
          <div className="rounded-xl border border-white/[0.065] bg-black/15 p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] uppercase tracking-[0.14em] text-white/28">{t("systemStatus")}</span>
              <span className={`size-1.5 rounded-full ${connected ? "bg-signal-400 shadow-[0_0_8px_#54e6b5]" : "bg-amber-400"}`} />
            </div>
            <div className="mt-2 flex items-center gap-2 text-xs text-white/60">
              <Icon name={connected ? "wifi" : "wifi-off"} size={14} />
              {connected ? t("wsLive") : t("wsOffline")}
            </div>
          </div>
          <a
            href="https://github.com/1ove9/yaf-goai-semifinal"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 px-3 py-2 text-xs text-white/35 transition-colors hover:text-white/75"
          >
            <Icon name="github" size={15} />
            <span>1ove9/yaf-goai-semifinal</span>
            <Icon name="external" size={12} className="ml-auto" />
          </a>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 border-b border-white/[0.065] bg-ink-950/80 backdrop-blur-xl">
          <div className="flex h-[72px] items-center gap-4 px-4 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3 lg:hidden">
              <BrandMark />
              <span className="text-sm font-semibold">YAF</span>
            </div>
            <div className="hidden min-w-0 flex-1 sm:block">
              <div className="mb-0.5 flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-white/28">
                <span>{t("projectName")}</span>
                <span>/</span>
                <span className="text-signal-300/70">{t(activeMeta.label)}</span>
              </div>
              <h1 className="truncate text-[17px] font-semibold tracking-[-0.025em]">{t(activeMeta.title)}</h1>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <div className="hidden items-center gap-2 rounded-full border border-white/[0.07] bg-white/[0.025] px-3 py-1.5 font-mono text-[10px] text-white/42 sm:flex">
                <span className={`size-1.5 rounded-full ${connected ? "bg-signal-400" : "bg-white/25"}`} />
                {connected ? t("connected") : t("disconnected")}
              </div>
              <div className="flex rounded-lg border border-white/[0.07] bg-white/[0.025] p-0.5" aria-label={t("language")}>
                <button
                  className={`rounded-md px-2.5 py-1.5 text-[10px] font-semibold transition-colors ${lang === "zh" ? "bg-white/10 text-white" : "text-white/35 hover:text-white/70"}`}
                  onClick={() => setLang("zh")}
                >
                  中文
                </button>
                <button
                  className={`rounded-md px-2.5 py-1.5 text-[10px] font-semibold transition-colors ${lang === "en" ? "bg-white/10 text-white" : "text-white/35 hover:text-white/70"}`}
                  onClick={() => setLang("en")}
                >
                  EN
                </button>
              </div>
            </div>
          </div>

          <nav className="flex gap-1 overflow-x-auto border-t border-white/[0.045] px-3 py-2 lg:hidden" aria-label={t("primaryNavigation")}>
            {(Object.entries(PAGE_META) as [Page, PageMeta][]).map(([key, meta]) => (
              <button
                key={key}
                onClick={() => setPage(key)}
                className={`flex min-w-max items-center gap-2 rounded-lg px-3 py-2 text-xs transition-colors ${page === key ? "bg-signal-400/10 text-signal-300" : "text-white/40 hover:text-white/70"}`}
              >
                <Icon name={meta.icon} size={15} />
                {t(meta.label)}
              </button>
            ))}
          </nav>
        </header>

        <main className="mx-auto w-full max-w-[1540px] p-4 sm:p-6 lg:p-8">
          <div className="mb-6 hidden max-w-2xl sm:block">
            <p className="text-sm leading-6 text-white/42">{t(activeMeta.description)}</p>
          </div>
          <React.Suspense
            fallback={
              <div className="grid min-h-[420px] place-items-center rounded-2xl border border-white/[0.06] bg-ink-850/70">
                <span className="size-5 animate-spin rounded-full border-2 border-white/10 border-t-signal-400" />
              </div>
            }
          >
            <div key={page} className="page-enter">{pageContent}</div>
          </React.Suspense>
        </main>
      </div>
    </div>
  );
};

const App: React.FC = () => (
  <SocketProvider>
    <Shell />
  </SocketProvider>
);

export default App;
