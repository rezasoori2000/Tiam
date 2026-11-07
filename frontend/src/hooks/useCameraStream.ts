import { useEffect, useRef, useState } from "react";
import { buildWsUrl } from "../lib/ws";

export type StreamState = "connecting" | "streaming" | "disconnected";

const RECONNECT_MS = 3000;

export function useCameraStream(cameraId: number) {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [state, setState] = useState<StreamState>("connecting");
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (cancelled) return;
      setState("connecting");
      socket = new WebSocket(buildWsUrl(`/ws/stream/${cameraId}`));
      socket.binaryType = "blob";

      socket.onopen = () => setState("streaming");
      socket.onmessage = (event) => {
        const blob: Blob = event.data;
        const nextUrl = URL.createObjectURL(blob);
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = nextUrl;
        setFrameUrl(nextUrl);
      };
      socket.onclose = () => {
        setState("disconnected");
        if (!cancelled) reconnectTimer = setTimeout(connect, RECONNECT_MS);
      };
      socket.onerror = () => socket?.close();
    };
    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer);
      socket?.close();
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    };
  }, [cameraId]);

  return { frameUrl, state };
}
