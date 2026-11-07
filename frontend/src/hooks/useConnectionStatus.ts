import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { buildWsUrl } from "../lib/ws";

export interface ConnectionStatus {
  apiOnline: boolean;
  wsConnected: boolean;
}

const HEALTH_POLL_MS = 10_000;
const WS_RECONNECT_MS = 3_000;

export function useConnectionStatus(): ConnectionStatus {
  const [apiOnline, setApiOnline] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;

    const checkHealth = async () => {
      try {
        await api.get("/api/health");
        if (!cancelled) setApiOnline(true);
      } catch {
        if (!cancelled) setApiOnline(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, HEALTH_POLL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (cancelled) return;
      const socket = new WebSocket(buildWsUrl("/ws/alerts"));
      socketRef.current = socket;

      socket.onopen = () => setWsConnected(true);
      socket.onclose = () => {
        setWsConnected(false);
        if (!cancelled) reconnectTimer = setTimeout(connect, WS_RECONNECT_MS);
      };
      socket.onerror = () => socket.close();
    };
    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      socketRef.current?.close();
    };
  }, []);

  return { apiOnline, wsConnected };
}
