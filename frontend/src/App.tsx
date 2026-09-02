import React, { useState } from "react";
import { Icon, IconName } from "./components/Icons";
import { MsgKey, useI18n } from "./i18n";
import { DesignContextProvider } from "./lib/designContext";
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
  <span
    className="relative grid size-10 flex-none place-items-center overflow-hidden rounded-[14px] border border-white/15 bg-white/[0.08] text-[#d6e2f2] shadow-[inset_0_1px_0_rgba(255,255,255,.22),0_14px_28px_-16px_rgba(169,196,232,.75)]"
    aria-hidden="true"
  >
    <svg viewBox="0 0 32 32" className="size-7">
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

const Shell: React.FC = () => {
  const [page, setPage] = useState<Page>("discover");
  const { lang, setLang, t, tEn } = useI18n();
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
    <div className="wall min-h-screen text-[#ededf0]">
      <span className="blob b1" aria-hidden="true" />
      <span className="blob b2" aria-hidden="true" />
      <span className="blob b3" aria-hidden="true" />

      <aside className="glass fixed inset-y-4 left-4 z-40 hidden w-[232px] flex-col px-[14px] pb-4 pt-[22px] lg:flex">
        <div className="flex items-center gap-3 px-2">
          <BrandMark />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[15px] font-semibold tracking-[-0.02em]">YAF</span>
              <span className="chip">alpha</span>
            </div>
            <p className="truncate font-serif text-[12px] italic text-white/[0.52]">Antenna Forge</p>
          </div>
        </div>

        <div className="mt-7 px-2">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/[0.44]">{t("workspace")}</p>
          <div className="flex w-full items-center gap-3 rounded-[18px] border border-white/[0.11] bg-white/[0.035] p-2.5">
            <span className="grid size-8 place-items-center rounded-[12px] bg-[rgba(169,196,232,.12)] text-[#d6e2f2]">
              <Icon name="radio" size={16} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-white/[0.88]">{t("projectName")}</span>
              <span className="mt-0.5 block font-mono text-[9px] uppercase tracking-wider text-white/[0.44]">{t("projectType")}</span>
            </span>
          </div>
        </div>

        <nav className="mt-7 space-y-1" aria-label={t("primaryNavigation")}>
          {(Object.entries(PAGE_META) as [Page, PageMeta][]).map(([key, meta]) => {
            const active = page === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setPage(key)}
                aria-current={active ? "page" : undefined}
                className={`navitem ${active ? "active" : ""}`}
              >
                <Icon name={meta.icon} size={17} />
                <span>{t(meta.label)}</span>
              </button>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3">
          <div className="status space-y-2.5">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-white/[0.44]">{t("systemStatus")}</span>
              <span className={`chip ${connected ? "ice" : ""}`}>
                {connected ? t("live") : t("checking")}
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs text-white/[0.68]">
              <Icon name={connected ? "wifi" : "wifi-off"} size={14} />
              {connected ? t("wsLive") : t("wsOffline")}
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px] text-white/[0.44]">
              <span className="size-1.5 rounded-full bg-white/30" />
              API · /api/v1
            </div>
          </div>
          <div className="flex items-center justify-between px-3 font-mono text-[9px] uppercase tracking-[0.12em] text-white/[0.44]">
            <span>v0.1 · alpha</span>
            <span>MIT</span>
          </div>
          <a
            href="https://github.com/1ove9/yaf-goai-semifinal"
            target="_blank"
            rel="noreferrer"
            className="btn-ghost flex w-full items-center gap-2"
          >
            <Icon name="github" size={15} />
            <span className="truncate">1ove9/yaf-goai-semifinal</span>
            <Icon name="external" size={12} className="ml-auto" />
          </a>
        </div>
      </aside>

      <div className="relative z-[1] min-h-screen lg:ml-[248px]">
        <header className="glass sticky top-4 z-30 mx-4 h-14 sm:mx-6 lg:ml-4 lg:mr-4">
          <div className="flex h-full items-center gap-4 px-4 sm:px-6">
            <div className="flex items-center gap-3 lg:hidden">
              <BrandMark />
              <span className="text-sm font-semibold">YAF</span>
            </div>
            <div className="hidden min-w-0 flex-1 sm:block">
              <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-white/[0.44]">
                <span>{t("projectName")}</span>
                <span>/</span>
                <span className="text-[#d6e2f2]">{t(activeMeta.label)}</span>
              </div>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <span className={`chip hidden sm:inline-flex ${connected ? "ice" : ""}`}>
                {connected ? t("connected") : t("disconnected")}
              </span>
              <div className="toggle" role="group" aria-label={t("language")}>
                <button
                  type="button"
                  className={lang === "zh" ? "on" : ""}
                  aria-pressed={lang === "zh"}
                  onClick={() => setLang("zh")}
                >
                  中文
                </button>
                <button
                  type="button"
                  className={lang === "en" ? "on" : ""}
                  aria-pressed={lang === "en"}
                  onClick={() => setLang("en")}
                >
                  EN
                </button>
              </div>
            </div>
          </div>
        </header>

        <nav className="glass sticky top-20 z-20 mx-4 mt-6 px-2 py-2 sm:mx-6 lg:hidden" aria-label={t("primaryNavigation")}>
          <div className="flex gap-1 overflow-x-auto">
            {(Object.entries(PAGE_META) as [Page, PageMeta][]).map(([key, meta]) => {
              const active = page === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setPage(key)}
                  aria-current={active ? "page" : undefined}
                  className={`navitem min-w-max ${active ? "active" : ""}`}
                >
                  <Icon name={meta.icon} size={15} />
                  {t(meta.label)}
                </button>
              );
            })}
          </div>
        </nav>

        <main className="mx-auto w-full max-w-[1540px] px-4 pb-8 pt-6 sm:px-6 lg:px-4 lg:pt-8">
          <section className="mb-7 max-w-3xl">
            <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h1 className="text-[28px] font-semibold tracking-[-0.025em] text-[#ededf0]">{t(activeMeta.title)}</h1>
              {lang === "zh" ? (
                <span className="font-serif text-[16px] italic text-white/[0.52]">{tEn(activeMeta.title)}</span>
              ) : null}
            </div>
            <p className="text-sm leading-6 text-white/[0.68]">{t(activeMeta.description)}</p>
          </section>

          <React.Suspense
            fallback={
              <div className="glass well grid min-h-[420px] place-items-center">
                <span className="size-5 animate-spin rounded-full border-2 border-white/10 border-t-[#a9c4e8] motion-reduce:animate-none" />
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
    <DesignContextProvider>
      <Shell />
    </DesignContextProvider>
  </SocketProvider>
);

export default App;
