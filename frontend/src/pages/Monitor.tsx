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
  chipLabel: string;
  live?: boolean;
}

const toneClasses: Record<StatusCardProps["tone"], string> = {
  green: "chip ice",
  amber: "chip gold",
  red: "chip coral",
  neutral: "chip",
};

const StatusCard: React.FC<StatusCardProps> = ({ icon, label, value, description, tone, chipLabel, live = false }) => (
  <article className={`glass tile ${live ? "live" : ""}`}>
    <div className="flex items-center justify-between gap-3 text-white/50">
      <Icon name={icon} size={18} />
      <span className={`${toneClasses[tone]} ${live ? "breathe" : ""}`}>{chipLabel}</span>
    </div>
    <p className="tile-label mt-4">{label}</p>
    <p className="tile-value">{value}</p>
    <p className="mt-1 text-[11px] leading-5 text-white/45">{description}</p>
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
          chipLabel={connected ? "Live" : t("disconnected")}
          live={connected}
        />
        <StatusCard
          icon="activity"
          label={t("apiHealth")}
          value={healthValue}
          description={healthDescription}
          tone={health === "healthy" ? "green" : health === "unreachable" ? "red" : "amber"}
          chipLabel={health === "healthy" ? "200 OK" : healthValue}
        />
        <StatusCard
          icon="signal"
          label={t("eventsReceived")}
          value={String(events.length).padStart(2, "0")}
          description={events.length > 0 ? `${events[0].type} · ${events[0].time}` : t("noEventsHint")}
          tone="neutral"
          chipLabel={t("sessionChip")}
        />
      </div>

      <section className="glass">
        <div className="phead h-auto min-h-14 py-3">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="eyebrow">{t("eventLog")}</h2>
                {connected ? <span className="chip ice breathe">{t("live")}</span> : null}
              </div>
              <p className="mt-0.5 text-[10px] text-white/30">{t("eventLogHint")}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden font-mono text-[10px] text-white/40 sm:inline">ws://{location.host}/ws</span>
          <button type="button" onClick={refresh} aria-label={t("refresh")} className="btn-ghost">
            <Icon name="refresh" size={13} className={health === "checking" ? "animate-spin" : ""} />
            <span className="hidden sm:inline">{t("refresh")}</span>
          </button>
          </div>
        </div>

        {events.length === 0 ? (
          <div className="grid min-h-[360px] place-items-center px-6 py-16 text-center">
            <div className="max-w-sm">
              <span className="mx-auto grid size-12 place-items-center rounded-[18px] border border-white/10 bg-white/[0.05] text-[#a9c4e8]"><Icon name="terminal" size={21} /></span>
              <h3 className="mt-4 text-sm font-semibold text-white/68">{t("noEvents")}</h3>
              <p className="mt-2 text-xs leading-5 text-white/30">{t("noEventsHint")}</p>
            </div>
          </div>
        ) : (
          <div className="max-h-[520px] overflow-auto font-mono text-[11px]">
            <div className="event-head sticky top-0 bg-[#141416]/95 backdrop-blur">
              <span>Time</span><span>Event</span><span>Message</span>
            </div>
            {events.map((event, index) => (
              <div key={`${event.time}-${event.type}-${index}`} className={`row ${index === 0 ? "new" : ""}`}>
                <span className="text-white/24">{event.time}</span>
                <span className="truncate pr-3 text-[#d6e2f2]">{event.type}</span>
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
