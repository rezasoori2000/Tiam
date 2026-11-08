import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Maximize2, Minimize2, RotateCw, VideoOff, X } from "lucide-react";
import { api } from "../lib/api";
import { useCameraStream } from "../hooks/useCameraStream";
import { useAlertToasts } from "../hooks/useAlertToasts";
import { riskLevel } from "./CoachingWorkbench";
import VlmChip from "../components/VlmChip";
import type { Camera, CameraStatus, CameraStatusResponse, Zone } from "../types";

// Alert queue item: 4px left border by severity (same thresholds as riskLevel).
const RISK_BORDER = (score: number) => {
  if (score >= 8)
    return "border-l-critical [animation:slide-in-right_200ms_ease-out,alert-pulse_1.6s_ease-in-out_200ms_infinite]";
  if (score >= 5) return "border-l-warning animate-slide-in-right";
  return "border-l-success animate-slide-in-right";
};

const STATUS_LABEL: Record<CameraStatus, string> = {
  connected: "Live",
  starting: "Starting...",
  reconnecting: "Reconnecting...",
  stopped: "Stopped",
  error: "Error",
};

const STATUS_DOT: Record<CameraStatus, string> = {
  connected: "bg-emerald-400",
  starting: "bg-amber-400",
  reconnecting: "bg-amber-400",
  stopped: "bg-slate-400",
  error: "bg-red-500",
};

const STATUS_POLL_MS = 3000;

// Same palette and order the backend used when it drew zones into the stream
// (config_loader.ZONE_COLORS, BGR there), so a zone keeps its colour.
const ZONE_COLORS = ["#ff0000", "#ffc800", "#c800ff", "#96ff00", "#0096ff"];

// Matches the backend's fixed processing frame; zone points are in this space.
const FRAME_W = 960;
const FRAME_H = 540;

function ZoneOverlay({ zones }: { zones: Zone[] }) {
  return (
    <svg
      viewBox={`0 0 ${FRAME_W} ${FRAME_H}`}
      preserveAspectRatio="xMidYMid meet"
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      {zones.map((zone, i) => {
        const color = ZONE_COLORS[i % ZONE_COLORS.length];
        const points = zone.polygon_points.map((p) => p.join(",")).join(" ");
        const [lx, ly] = zone.polygon_points[0] ?? [0, 0];
        return (
          <g key={zone.id}>
            <polygon points={points} fill={color} fillOpacity={0.15} stroke={color} strokeWidth={2} />
            <text x={lx} y={ly} fill={color} fontSize={14} fontWeight={600}>
              {zone.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function CameraTile({
  camera,
  isFullscreen,
  alerting,
  onToggleFullscreen,
}: {
  camera: Camera;
  isFullscreen: boolean;
  alerting: boolean;
  onToggleFullscreen: () => void;
}) {
  const { frameUrl } = useCameraStream(camera.id);
  const [status, setStatus] = useState<CameraStatusResponse>({ status: "starting", last_error: null });
  const [restarting, setRestarting] = useState(false);
  // Zone outlines are off by default; fetched when switched on so edits made in
  // Zone Studio show up the next time it's toggled.
  const [showZones, setShowZones] = useState(false);
  const [zones, setZones] = useState<Zone[]>([]);

  useEffect(() => {
    if (!showZones) return;
    let cancelled = false;
    api
      .get<Zone[]>("/api/zones", { params: { camera_id: camera.id } })
      .then((res) => !cancelled && setZones([...res.data].sort((a, b) => a.id - b.id)))
      .catch(() => !cancelled && setZones([]));
    return () => {
      cancelled = true;
    };
  }, [showZones, camera.id]);

  useEffect(() => {
    if (!isFullscreen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onToggleFullscreen();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isFullscreen, onToggleFullscreen]);

  const pollStatus = useCallback(async () => {
    try {
      const res = await api.get<CameraStatusResponse>(`/api/cameras/${camera.id}/status`);
      setStatus(res.data);
    } catch {
      setStatus({ status: "error", last_error: "status unavailable" });
    }
  }, [camera.id]);

  useEffect(() => {
    pollStatus();
    const interval = setInterval(pollStatus, STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [pollStatus]);

  async function handleRestart() {
    setRestarting(true);
    try {
      await api.post(`/api/cameras/${camera.id}/restart`);
      await pollStatus();
    } finally {
      setRestarting(false);
    }
  }

  const stale = status.status !== "connected";

  return (
    <div
      className={`${
        isFullscreen
          ? "fixed inset-0 z-50 flex flex-col bg-black"
          : "overflow-hidden rounded border border-line bg-panel"
      } ${alerting ? "outline outline-2 outline-critical" : ""}`}
    >
      <div className={isFullscreen ? "relative flex-1 bg-black" : "relative aspect-video bg-black"}>
        {frameUrl ? (
          <img
            src={frameUrl}
            alt={camera.name}
            className={`h-full w-full object-contain transition-opacity ${stale ? "opacity-40" : ""}`}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-b from-[var(--video-from)] to-[var(--video-to)] text-muted">
            <VideoOff className="h-8 w-8" />
          </div>
        )}
        {showZones && frameUrl && <ZoneOverlay zones={zones} />}
        <span className="absolute left-2 top-2 z-10 max-w-[60%] truncate rounded bg-black/60 px-1.5 py-0.5 text-[11px] font-medium text-fg">
          {camera.name}
        </span>
        <div className="absolute right-2 top-2 z-10 flex gap-1">
          {alerting && <span className="dm-chip-critical animate-alert-pulse">Alert</span>}
          {status.status === "connected" && <span className="dm-chip-critical">Live</span>}
        </div>
        {stale && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/30 text-slate-100">
            <span className="text-sm font-medium">{STATUS_LABEL[status.status]}</span>
            <button
              onClick={handleRestart}
              disabled={restarting}
              className="flex items-center gap-1.5 rounded-lg bg-panel-2 px-3 py-1.5 text-xs font-medium text-fg hover:bg-line disabled:opacity-50"
            >
              <RotateCw className={`h-3.5 w-3.5 ${restarting ? "animate-spin" : ""}`} />
              Restart camera
            </button>
          </div>
        )}
      </div>
      <div
        className={`flex items-center justify-between border-b border-slate-800 ${
          isFullscreen ? "bg-apl-midnight px-4 py-2" : "px-3 py-1.5"
        }`}
      >
        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
          <button
            type="button"
            role="switch"
            aria-checked={showZones}
            onClick={() => setShowZones((v) => !v)}
            className={`relative h-4 w-7 rounded-full transition-colors ${
              showZones ? "bg-apl-sunset" : "bg-slate-600"
            }`}
          >
            <span
              className={`absolute top-0.5 h-3 w-3 rounded-full bg-fg transition-all ${
                showZones ? "left-3.5" : "left-0.5"
              }`}
            />
          </button>
          <span>Show zones</span>
        </label>
        {showZones && (
          <span className="text-xs text-slate-500">
            {zones.length} zone{zones.length === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <div className={`flex items-center justify-between ${isFullscreen ? "bg-apl-midnight px-4 py-3" : "px-3 py-2"}`}>
        <span className={isFullscreen ? "text-base font-medium text-slate-100" : "text-sm font-medium text-slate-100"}>
          {camera.name}
        </span>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-xs text-slate-300">
            <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status.status]}`} />
            {STATUS_LABEL[status.status]}
          </span>
          <button
            onClick={handleRestart}
            disabled={restarting}
            className="text-slate-400 hover:text-apl-sunset disabled:opacity-50"
            title="Restart camera worker"
          >
            <RotateCw className={`h-3.5 w-3.5 ${restarting ? "animate-spin" : ""}`} />
          </button>
          <button
            onClick={onToggleFullscreen}
            className="text-slate-400 hover:text-apl-sunset"
            title={isFullscreen ? "Exit full screen" : "View full screen"}
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function LiveMonitor() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [fullscreenId, setFullscreenId] = useState<number | null>(null);
  const { toasts, dismiss } = useAlertToasts();

  useEffect(() => {
    api.get<Camera[]>("/api/cameras").then((res) => {
      setCameras(res.data.filter((c) => c.is_enabled));
      setLoading(false);
    });
  }, []);

  return (
    <div>
      <h2 className="text-xl font-semibold text-slate-100">Live Monitor</h2>
      <p className="mt-1 text-sm text-slate-400">
        Live annotated feed from every enabled camera.
      </p>

      <div className="pointer-events-none fixed right-4 top-16 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.toastId}
            className={`pointer-events-auto flex items-start gap-2 rounded border border-l-4 border-line bg-panel-2 px-3 py-2 text-fg ${RISK_BORDER(toast.risk_score)}`}
          >
            <AlertTriangle
              className={`mt-0.5 h-4 w-4 flex-shrink-0 ${
                toast.risk_score >= 8 ? "text-critical" : toast.risk_score >= 5 ? "text-warning" : "text-success"
              }`}
            />
            <div className="flex-1 text-sm">
              <div className="flex flex-wrap items-center gap-1.5 font-semibold">
                {toast.policy_type}
                <VlmChip status={toast.vlm_status} verdict={toast.vlm_verdict} confidence={toast.vlm_confidence} />
              </div>
              <div className="text-xs text-muted">
                {toast.zone_name} &middot; {riskLevel(toast.risk_score)} risk ({toast.risk_score}/10) &middot;{" "}
                {new Date(toast.timestamp).toLocaleTimeString()}
              </div>
            </div>
            <button onClick={() => dismiss(toast.toastId)} className="text-muted hover:text-fg" aria-label="Dismiss alert">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      <div className="mt-6">
        {loading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Loading cameras">
            {[0, 1, 2].map((i) => (
              <div key={i} className="dm-skeleton aspect-video" />
            ))}
          </div>
        ) : cameras.length === 0 ? (
          <p className="text-sm text-slate-400">
            No enabled cameras yet. Add one in the Cameras page.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {cameras.map((camera) => (
              <CameraTile
                key={camera.id}
                camera={camera}
                isFullscreen={camera.id === fullscreenId}
                alerting={toasts.some((t) => t.camera_id === camera.id)}
                onToggleFullscreen={() =>
                  setFullscreenId((id) => (id === camera.id ? null : camera.id))
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
