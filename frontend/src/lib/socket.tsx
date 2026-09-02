import React, { createContext, useContext, useEffect, useRef, useState } from "react";

export interface SimEvent {
  time: string;
  type: string;
  message: string;
}

interface SocketState {
  connected: boolean;
  events: SimEvent[];
  lastEvent: SimEvent | null;
}

const SocketContext = createContext<SocketState | null>(null);

const RECONNECT_MS = 4000;
const MAX_EVENTS = 200;

/**
 * Single app-wide WebSocket to the simulation progress channel, with
 * automatic reconnect and a bounded event log shared by all pages.
 */
export const SocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<SimEvent[]>([]);
  const [lastEvent, setLastEvent] = useState<SimEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/simulation/demo`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closedRef.current) {
          timerRef.current = window.setTimeout(connect, RECONNECT_MS);
        }
      };
      ws.onmessage = (raw) => {
        let type = "message";
        let message = raw.data as string;
        try {
          const data = JSON.parse(raw.data as string);
          type = data.type ?? "message";
          message = data.message ?? JSON.stringify(data);
        } catch {
          /* plain-text frame — keep as-is */
        }
        const event: SimEvent = {
          time: new Date().toLocaleTimeString(),
          type,
          message,
        };
        setLastEvent(event);
        setEvents((prev) => [event, ...prev].slice(0, MAX_EVENTS));
      };
    };

    connect();
    return () => {
      closedRef.current = true;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, []);

  return (
    <SocketContext.Provider value={{ connected, events, lastEvent }}>
      {children}
    </SocketContext.Provider>
  );
};

export function useSocket(): SocketState {
  const ctx = useContext(SocketContext);
  if (!ctx) throw new Error("useSocket must be used inside <SocketProvider>");
  return ctx;
}
