import React, { useEffect, useState } from "react";
import { Icon, IconName } from "../components/Icons";
import { useI18n } from "../i18n";
import { useSocket } from "../lib/socket";

const HEALTH_POLL_MS = 10_000;
type Health = "checking" | "healthy" | "unreachable";

interface StatusCardProps {
  icon: IconName;
  label: string;
  value: string;
  description: string;
  tone: "green" | "amber" | "red" | "neutral";
}

const toneClasses: Record<StatusCardProps["tone"], string> = {
  green: "bg-signal-400 text-ink-950 shadow-[0_0_14px_rgba(84,230,181,0.24)]",
  amber: "bg-amber-300 text-ink-950",
  red: "bg-red-400 text-white",
  neutral: "bg-white/20 text-white",
};

const StatusCard: React.FC<StatusCardProps> = ({ icon, label, value, description, tone }) => (
  <article className="panel-highlight relative overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 p-5 shadow-panel">
    <div className="flex items-start justify-between gap-4">
      <span className="grid size-9 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.03] text-white/45"><Icon name={icon} size={17} /></span>
      <span className={`mt-1 size-2 rounded-full ${toneClasses[tone]}`} />
    </div>
    <p className="mt-6 text-[10px] font-semibold uppercase tracking-[0.15em] text-white/28">{label}</p>
    <p className="mt-2 text-xl font-semibold tracking-[-0.03em] text-white/88">{value}</p>
    <p className="mt-1.5 text-[11px] leading-5 text-white/32">{description}</p>
  </article>
);

const Monitor: React.FC = () => {
  const { t } = useI18n();
  const { connected, events } = useSocket();
  const [health, setHealth] = useState<Health>("checking");
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const response = await fetch("/health");
        if (!cancelled) setHealth(response.ok ? "healthy" : "unreachable");
      } catch {
        if (!cancelled) setHealth("unreachable");
      }
    };
    void check();
    const timer = window.setInterval(check, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshToken]);

  const refresh = () => {
    setHealth("checking");
    setRefreshToken((current) => current + 1);
  };

  const healthValue = health === "checking" ? t("checking") : health === "healthy" ? t("healthy") : t("unreachable");
  const healthDescription = health === "healthy" ? t("serviceOnline") : health === "unreachable" ? t("serviceOffline") : t("checking");

  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-3">
        <StatusCard
          icon={connected ? "wifi" : "wifi-off"}
          label={t("websocket")}
          value={connected ? t("connected") : t("disconnected")}
          description={connected ? t("streamOnline") : t("streamOffline")}
          tone={connected ? "green" : "amber"}
        />
        <StatusCard
          icon="activity"
          label={t("apiHealth")}
          value={healthValue}
          description={healthDescription}
          tone={health === "healthy" ? "green" : health === "unreachable" ? "red" : "amber"}
        />
        <StatusCard
          icon="signal"
          label={t("eventsReceived")}
          value={String(events.length).padStart(2, "0")}
          description={events.length > 0 ? `${events[0].type} · ${events[0].time}` : t("noEventsHint")}
          tone={events.length > 0 ? "green" : "neutral"}
        />
      </div>

      <section className="overflow-hidden rounded-2xl border border-white/[0.07] bg-ink-850 shadow-panel">
        <div className="flex items-center justify-between gap-4 border-b border-white/[0.06] px-4 py-4 sm:px-5">
          <div className="flex items-center gap-3">
            <span className="grid size-8 place-items-center rounded-lg bg-white/[0.035] text-white/45"><Icon name="terminal" size={16} /></span>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-semibold text-white/85">{t("eventLog")}</h2>
                {connected ? <span className="rounded-full border border-signal-400/20 bg-signal-400/[0.07] px-2 py-0.5 font-mono text-[8px] uppercase tracking-widest text-signal-300">{t("live")}</span> : null}
              </div>
              <p className="mt-0.5 text-[10px] text-white/30">{t("eventLogHint")}</p>
            </div>
          </div>
          <button onClick={refresh} className="flex items-center gap-2 rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2 text-[10px] font-medium text-white/42 transition-colors hover:bg-white/[0.055] hover:text-white/75">
            <Icon name="refresh" size={13} className={health === "checking" ? "animate-spin" : ""} />
            <span className="hidden sm:inline">{t("refresh")}</span>
          </button>
        </div>

        {events.length === 0 ? (
          <div className="grid min-h-[360px] place-items-center px-6 py-16 text-center">
            <div className="max-w-sm">
              <span className="mx-auto grid size-12 place-items-center rounded-2xl border border-white/[0.07] bg-white/[0.025] text-white/25"><Icon name="terminal" size={21} /></span>
              <h3 className="mt-4 text-sm font-semibold text-white/68">{t("noEvents")}</h3>
              <p className="mt-2 text-xs leading-5 text-white/30">{t("noEventsHint")}</p>
            </div>
          </div>
        ) : (
          <div className="max-h-[520px] overflow-auto font-mono text-[11px]">
            <div className="sticky top-0 grid grid-cols-[78px_100px_minmax(0,1fr)] border-b border-white/[0.055] bg-ink-850/95 px-4 py-2.5 uppercase tracking-wider text-white/22 backdrop-blur sm:grid-cols-[92px_130px_minmax(0,1fr)] sm:px-5">
              <span>Time</span><span>Event</span><span>Message</span>
            </div>
            {events.map((event, index) => (
              <div key={`${event.time}-${event.type}-${index}`} className="grid grid-cols-[78px_100px_minmax(0,1fr)] border-b border-white/[0.045] px-4 py-3 text-white/42 transition-colors last:border-0 hover:bg-white/[0.018] sm:grid-cols-[92px_130px_minmax(0,1fr)] sm:px-5">
                <span className="text-white/24">{event.time}</span>
                <span className="truncate pr-3 text-signal-300/65">{event.type}</span>
                <span className="break-words leading-5 text-white/52">{event.message}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};

export default Monitor;
