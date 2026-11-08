import { useEffect, useRef, useState } from "react";
import { buildWsUrl } from "../lib/ws";
import type { AlertPayload, VerificationUpdate } from "../types";

export interface Toast extends AlertPayload {
  toastId: string;
}

const TOAST_LIFETIME_MS = 6000;
const RECONNECT_MS = 3000;

export function useAlertToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  function dismiss(toastId: string) {
    setToasts((prev) => prev.filter((t) => t.toastId !== toastId));
    const timer = timersRef.current.get(toastId);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(toastId);
    }
  }

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (cancelled) return;
      socket = new WebSocket(buildWsUrl("/ws/alerts"));
      socket.onmessage = (event) => {
        const message: AlertPayload | VerificationUpdate = JSON.parse(event.data);
        if ("kind" in message && message.kind === "verification") {
          // A late AI verdict: update the alert's toast if it's still on screen.
          const { kind: _kind, ...update } = message;
          setToasts((prev) => prev.map((t) => (t.event_id === message.event_id ? { ...t, ...update } : t)));
          return;
        }
        const payload = message as AlertPayload;
        const toastId = `${payload.event_id}-${payload.timestamp}`;
        setToasts((prev) => [...prev, { ...payload, toastId }]);
        const timer = setTimeout(() => dismiss(toastId), TOAST_LIFETIME_MS);
        timersRef.current.set(toastId, timer);
      };
      socket.onclose = () => {
        if (!cancelled) reconnectTimer = setTimeout(connect, RECONNECT_MS);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      socket?.close();
      timersRef.current.forEach(clearTimeout);
    };
  }, []);

  return { toasts, dismiss };
}
