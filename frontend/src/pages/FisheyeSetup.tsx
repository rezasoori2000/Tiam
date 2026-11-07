import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Loader2, Plus, RefreshCw, RotateCcw, Save, Trash2, Wand2, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { token } from "../lib/theme";
import type { Camera, FisheyeViewPayload, Point } from "../types";

const HANDLE_SIZE = 8;
const ELLIPSE_COLOR = token("success");
const VIEW_COLORS = ["#f07864", "#38bdf8", "#facc15", "#a78bfa", "#34d399", "#fb923c", "#f472b6", "#94a3b8"];
const MAX_VIEWS = 8;

// Mirrors backend app/fisheye.py DEFAULT_VIEW_*: one view per diagonal of the
// raw image, tilted out from straight down so each looks like a normal
// angled CCTV camera covering one side of the area.
const DEFAULT_DIRECTIONS = [315, 45, 135, 225];
const DEFAULT_TILT = 55;
const DEFAULT_FOV = 95;

type Box = { x0: number; y0: number; x1: number; y1: number };
type Circle = { cx: number; cy: number; rx: number; ry: number }; // ratios 0-1
type ViewDraft = FisheyeViewPayload & { key: string };

function normalize(box: Box): Box {
  return {
    x0: Math.min(box.x0, box.x1),
    y0: Math.min(box.y0, box.y1),
    x1: Math.max(box.x0, box.x1),
    y1: Math.max(box.y0, box.y1),
  };
}

let draftKey = 0;
function newKey() {
  draftKey += 1;
  return `v${draftKey}`;
}

function defaultViews(cameraName: string): ViewDraft[] {
  return DEFAULT_DIRECTIONS.map((direction, i) => ({
    key: newKey(),
    name: `${cameraName} - View ${i + 1}`,
    direction_deg: direction,
    tilt_deg: DEFAULT_TILT,
    fov_deg: DEFAULT_FOV,
  }));
}

function viewsFromCameras(views: Camera[]): ViewDraft[] {
  return views.map((v) => ({
    key: newKey(),
    id: v.id,
    name: v.name,
    direction_deg: v.view_direction_deg ?? 0,
    tilt_deg: v.view_tilt_deg ?? DEFAULT_TILT,
    fov_deg: v.view_fov_deg ?? DEFAULT_FOV,
  }));
}

// Server-rendered preview of one virtual view from the latest raw frame.
// Debounced so dragging a slider doesn't fire a request per pixel.
function ViewPreview({
  cameraId,
  view,
  circle,
  refreshKey,
}: {
  cameraId: number;
  view: ViewDraft;
  circle: Circle | null;
  refreshKey: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      const params = new URLSearchParams({
        camera_id: String(cameraId),
        direction: String(view.direction_deg),
        tilt: String(view.tilt_deg),
        fov: String(view.fov_deg),
      });
      if (circle) {
        params.set("cx", String(circle.cx));
        params.set("cy", String(circle.cy));
        params.set("rx", String(circle.rx));
        params.set("ry", String(circle.ry));
      }
      setLoading(true);
      api
        .get(`/api/camera/fisheye-view-preview?${params}`, { responseType: "blob" })
        .then((res) => {
          if (cancelled) return;
          const next = URL.createObjectURL(res.data as Blob);
          setUrl((prev) => {
            if (prev) URL.revokeObjectURL(prev);
            return next;
          });
          setError(null);
        })
        .catch(() => !cancelled && setError("No preview -- is the camera running?"))
        .finally(() => !cancelled && setLoading(false));
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [cameraId, view.direction_deg, view.tilt_deg, view.fov_deg, circle, refreshKey]);

  return (
    <div className="relative aspect-video overflow-hidden rounded-lg bg-slate-900">
      {url && <img src={url} alt={view.name} className="h-full w-full object-cover" />}
      {!url && (
        <div className="flex h-full items-center justify-center p-2 text-center text-xs text-slate-500">
          {error ?? "Loading preview..."}
        </div>
      )}
      {loading && url && (
        <Loader2 className="absolute right-2 top-2 h-4 w-4 animate-spin text-fg drop-shadow" />
      )}
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  unit,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  unit: string;
  hint?: string;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block text-xs">
      <div className="flex justify-between text-slate-400">
        <span>{label}</span>
        <span className="text-slate-300">
          {Math.round(value)}
          {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
      {hint && <div className="text-muted">{hint}</div>}
    </label>
  );
}

export default function FisheyeSetup() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);

  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);
  const [imgSize, setImgSize] = useState({ w: 960, h: 540 });

  const [box, setBox] = useState<Box | null>(null);
  const [circleDirty, setCircleDirty] = useState(false);
  const [detecting, setDetecting] = useState(false);
  const dragModeRef = useRef<"none" | "new" | "move" | "tl" | "br">("none");
  const dragStartRef = useRef<Point>([0, 0]);
  const boxAtDragStartRef = useRef<Box | null>(null);

  const [views, setViews] = useState<ViewDraft[]>([]);
  const [viewsExist, setViewsExist] = useState(false);
  const [previewRefresh, setPreviewRefresh] = useState(0);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  const camera = cameras.find((c) => c.id === cameraId);

  const loadCameras = useCallback(() => {
    return api.get<Camera[]>("/api/cameras").then((res) => {
      const fisheyeCameras = res.data.filter((c) => c.source_type === "fisheye");
      setCameras(fisheyeCameras);
      return fisheyeCameras;
    });
  }, []);

  useEffect(() => {
    loadCameras().then((fisheyeCameras) => {
      const fromUrl = Number(searchParams.get("camera"));
      if (fromUrl && fisheyeCameras.some((c) => c.id === fromUrl)) {
        setCameraId(fromUrl);
      } else if (fisheyeCameras.length > 0) {
        setCameraId(fisheyeCameras[0].id);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadSnapshot = useCallback((camId: number, attempt = 1) => {
    setLoadingSnapshot(true);
    setSnapshotError(null);
    api
      .get(`/api/camera/snapshot-raw?camera_id=${camId}`, { responseType: "blob" })
      .then((res) => {
        const url = URL.createObjectURL(res.data as Blob);
        setSnapshotUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return url;
        });
        setLoadingSnapshot(false);
      })
      .catch(() => {
        if (attempt < 5) {
          setTimeout(() => loadSnapshot(camId, attempt + 1), 1500);
        } else {
          setSnapshotError(
            "No frame from this camera yet. Start it on the Cameras page (or start one of its views) and check it shows \"connected\"."
          );
          setLoadingSnapshot(false);
        }
      });
  }, []);

  const loadViews = useCallback((cam: Camera) => {
    api.get<Camera[]>(`/api/cameras/${cam.id}/fisheye-views`).then((res) => {
      setViewsExist(res.data.length > 0);
      setViews(res.data.length > 0 ? viewsFromCameras(res.data) : defaultViews(cam.name));
    });
  }, []);

  useEffect(() => {
    if (cameraId == null || !camera) return;
    setSearchParams({ camera: String(cameraId) }, { replace: true });
    loadSnapshot(cameraId);
    loadViews(camera);
    setBox(null);
    setCircleDirty(false);
    setSavedMessage(null);
    setSaveError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, cameras.length]);

  useEffect(() => {
    if (!snapshotUrl) return;
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      setImgSize({ w: img.naturalWidth, h: img.naturalHeight });
      if (
        camera?.fisheye_center_x != null &&
        camera.fisheye_center_y != null &&
        camera.fisheye_radius_x != null &&
        camera.fisheye_radius_y != null
      ) {
        const cx = camera.fisheye_center_x * img.naturalWidth;
        const cy = camera.fisheye_center_y * img.naturalHeight;
        const rx = camera.fisheye_radius_x * img.naturalWidth;
        const ry = camera.fisheye_radius_y * img.naturalHeight;
        setBox((prev) => prev ?? { x0: cx - rx, y0: cy - ry, x1: cx + rx, y1: cy + ry });
      }
      draw();
    };
    img.src = snapshotUrl;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotUrl]);

  const normBox = box ? normalize(box) : null;
  const rxPx = normBox ? (normBox.x1 - normBox.x0) / 2 : 0;
  const ryPx = normBox ? (normBox.y1 - normBox.y0) / 2 : 0;
  const hasCircle = normBox != null && rxPx > 4 && ryPx > 4;

  // Unsaved circle, passed to the previews so they follow the drawn ellipse.
  const circleKey = normBox ? `${normBox.x0}|${normBox.y0}|${normBox.x1}|${normBox.y1}|${imgSize.w}|${imgSize.h}` : "";
  const [previewCircle, setPreviewCircle] = useState<Circle | null>(null);
  useEffect(() => {
    if (!hasCircle || !normBox || !circleDirty) {
      setPreviewCircle(null);
      return;
    }
    setPreviewCircle({
      cx: (normBox.x0 + normBox.x1) / 2 / imgSize.w,
      cy: (normBox.y0 + normBox.y1) / 2 / imgSize.h,
      rx: rxPx / imgSize.w,
      ry: ryPx / imgSize.h,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [circleKey, circleDirty]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (img) ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    else {
      ctx.fillStyle = token("video-to");
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    if (box) {
      const b = normalize(box);
      const cx = (b.x0 + b.x1) / 2;
      const cy = (b.y0 + b.y1) / 2;
      const rx = (b.x1 - b.x0) / 2;
      const ry = (b.y1 - b.y0) / 2;
      const lineW = Math.max(2, canvas.width / 400);

      // Where each view is pointing: a spoke from the centre, out to how far
      // it's tilted (0 = centre / straight down, 90 = lens edge / horizon).
      views.forEach((v, i) => {
        const a = ((v.direction_deg - 90) * Math.PI) / 180;
        const reach = v.tilt_deg / 90;
        const ex = cx + Math.cos(a) * rx * reach;
        const ey = cy + Math.sin(a) * ry * reach;
        ctx.strokeStyle = VIEW_COLORS[i % VIEW_COLORS.length];
        ctx.lineWidth = lineW * 1.5;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(ex, ey);
        ctx.stroke();
        ctx.fillStyle = VIEW_COLORS[i % VIEW_COLORS.length];
        ctx.beginPath();
        ctx.arc(ex, ey, lineW * 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = `bold ${Math.round(lineW * 10)}px sans-serif`;
        ctx.fillText(String(i + 1), ex + lineW * 5, ey - lineW * 5);
      });

      ctx.strokeStyle = ELLIPSE_COLOR;
      ctx.lineWidth = lineW;
      ctx.beginPath();
      ctx.ellipse(cx, cy, Math.max(rx, 0), Math.max(ry, 0), 0, 0, Math.PI * 2);
      ctx.stroke();

      const hs = Math.max(HANDLE_SIZE, canvas.width / 120);
      [[b.x0, b.y0], [b.x1, b.y1]].forEach(([x, y]) => {
        ctx.fillStyle = ELLIPSE_COLOR;
        ctx.fillRect(x - hs / 2, y - hs / 2, hs, hs);
        ctx.strokeStyle = token("bg");
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x - hs / 2, y - hs / 2, hs, hs);
      });
    }
  }, [box, views]);

  useEffect(() => {
    draw();
  }, [draw]);

  function toImageCoords(e: React.MouseEvent<HTMLCanvasElement>): Point {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return [(e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY];
  }

  function nearHandle(p: Point, hx: number, hy: number): boolean {
    const hs = Math.max(HANDLE_SIZE, (canvasRef.current?.width ?? 960) / 60);
    return Math.abs(p[0] - hx) <= hs && Math.abs(p[1] - hy) <= hs;
  }

  function pointInEllipse(p: Point, b: Box): boolean {
    const cx = (b.x0 + b.x1) / 2;
    const cy = (b.y0 + b.y1) / 2;
    const rx = (b.x1 - b.x0) / 2 || 1;
    const ry = (b.y1 - b.y0) / 2 || 1;
    const nx = (p[0] - cx) / rx;
    const ny = (p[1] - cy) / ry;
    return nx * nx + ny * ny <= 1;
  }

  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const p = toImageCoords(e);
    setSavedMessage(null);
    setCircleDirty(true);
    if (box) {
      const b = normalize(box);
      if (nearHandle(p, b.x0, b.y0)) {
        dragModeRef.current = "tl";
        boxAtDragStartRef.current = b;
        return;
      }
      if (nearHandle(p, b.x1, b.y1)) {
        dragModeRef.current = "br";
        boxAtDragStartRef.current = b;
        return;
      }
      if (pointInEllipse(p, b)) {
        dragModeRef.current = "move";
        dragStartRef.current = p;
        boxAtDragStartRef.current = b;
        return;
      }
    }
    dragModeRef.current = "new";
    dragStartRef.current = p;
    setBox({ x0: p[0], y0: p[1], x1: p[0], y1: p[1] });
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const p = toImageCoords(e);
    const mode = dragModeRef.current;
    if (mode === "new") {
      setBox((prev) => (prev ? { ...prev, x1: p[0], y1: p[1] } : prev));
    } else if (mode === "tl") {
      setBox((prev) => (prev ? { ...prev, x0: p[0], y0: p[1] } : prev));
    } else if (mode === "br") {
      setBox((prev) => (prev ? { ...prev, x1: p[0], y1: p[1] } : prev));
    } else if (mode === "move" && boxAtDragStartRef.current) {
      const start = dragStartRef.current;
      const orig = boxAtDragStartRef.current;
      const dx = p[0] - start[0];
      const dy = p[1] - start[1];
      setBox({ x0: orig.x0 + dx, y0: orig.y0 + dy, x1: orig.x1 + dx, y1: orig.y1 + dy });
    }
  }

  function handleMouseUp() {
    dragModeRef.current = "none";
    boxAtDragStartRef.current = null;
  }

  async function handleAutoDetect() {
    if (cameraId == null) return;
    setDetecting(true);
    setSaveError(null);
    try {
      const res = await api.post<{
        fisheye_center_x: number;
        fisheye_center_y: number;
        fisheye_radius_x: number;
        fisheye_radius_y: number;
      }>(`/api/cameras/${cameraId}/fisheye/detect-circle`);
      const c = res.data;
      const cx = c.fisheye_center_x * imgSize.w;
      const cy = c.fisheye_center_y * imgSize.h;
      const rx = c.fisheye_radius_x * imgSize.w;
      const ry = c.fisheye_radius_y * imgSize.h;
      setBox({ x0: cx - rx, y0: cy - ry, x1: cx + rx, y1: cy + ry });
      setCircleDirty(true);
      setSavedMessage(null);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : "Auto-detect failed");
    } finally {
      setDetecting(false);
    }
  }

  function updateView(key: string, patch: Partial<ViewDraft>) {
    setViews((prev) => prev.map((v) => (v.key === key ? { ...v, ...patch } : v)));
    setSavedMessage(null);
  }

  function addView() {
    if (!camera) return;
    setViews((prev) => [
      ...prev,
      {
        key: newKey(),
        name: `${camera.name} - View ${prev.length + 1}`,
        direction_deg: 0,
        tilt_deg: DEFAULT_TILT,
        fov_deg: DEFAULT_FOV,
      },
    ]);
  }

  function resetViews() {
    if (!camera) return;
    // Keep existing view ids (so their zones survive), just re-aim them.
    setViews((prev) => {
      const defaults = defaultViews(camera.name);
      return defaults.map((d, i) => (prev[i] ? { ...d, id: prev[i].id, name: prev[i].name } : d));
    });
    setSavedMessage(null);
  }

  async function handleSave() {
    if (cameraId == null || !camera) return;
    if (views.some((v) => !v.name.trim())) {
      setSaveError("Every view needs a name.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    setSavedMessage(null);
    try {
      // Views use the camera's saved lens circle, so save it first.
      if (hasCircle && normBox && circleDirty) {
        await api.put(`/api/cameras/${cameraId}`, {
          fisheye_center_x: (normBox.x0 + normBox.x1) / 2 / imgSize.w,
          fisheye_center_y: (normBox.y0 + normBox.y1) / 2 / imgSize.h,
          fisheye_radius_x: rxPx / imgSize.w,
          fisheye_radius_y: ryPx / imgSize.h,
        });
        setCircleDirty(false);
      }
      const res = await api.put<Camera[]>(`/api/cameras/${cameraId}/fisheye-views`, {
        views: views.map(({ id, name, direction_deg, tilt_deg, fov_deg }) => ({
          id,
          name: name.trim(),
          direction_deg,
          tilt_deg,
          fov_deg,
        })),
      });
      const firstTime = !viewsExist && res.data.length > 0;
      setViews(viewsFromCameras(res.data));
      setViewsExist(res.data.length > 0);
      await loadCameras();
      setSavedMessage(
        res.data.length === 0
          ? "Views removed."
          : `Saved ${res.data.length} view(s). Each is now its own camera in Live Monitor, Zone Studio and Calibration.` +
              (firstTime && camera.is_enabled
                ? ` Detection on the original "${camera.name}" camera was switched off so alerts aren't raised twice.`
                : "")
      );
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : "Failed to save views");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-7xl">
      <h2 className="text-xl font-semibold text-slate-100">Fisheye Setup</h2>
      <p className="mt-1 text-sm text-slate-400">
        Splits one fisheye camera into several normal-looking views, each flattened on its own and
        used as a separate camera, with its own name, zones and detection.
      </p>

      {cameras.length === 0 ? (
        <div className="dm-card mt-4 p-6 text-sm text-slate-400">
          No fisheye cameras yet. Add one from the <span className="text-slate-300">Cameras</span> page
          first (choose "Fisheye Camera" as the source type).
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap gap-3">
            <label className="text-sm">
              <span className="dm-label">Camera</span>
              <select
                value={cameraId ?? ""}
                onChange={(e) => setCameraId(Number(e.target.value))}
                className="dm-input w-56"
              >
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </label>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => {
                  if (cameraId == null) return;
                  loadSnapshot(cameraId);
                  setPreviewRefresh((n) => n + 1);
                }}
                className="dm-btn-secondary"
              >
                <RefreshCw className="h-4 w-4" /> Refresh frame
              </button>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,460px)_minmax(0,1fr)]">
            {/* Step 1: lens circle */}
            <div>
              <h3 className="text-sm font-semibold text-slate-200">1. Lens circle</h3>
              <p className="mb-2 text-xs text-slate-500">
                Auto-detect, or drag from one edge of the circle to the opposite edge. Drag a corner
                to resize, or inside to move. The coloured spokes show where each view points.
              </p>
              <div
                className="relative overflow-hidden rounded-xl border border-slate-800 bg-slate-900"
                style={{ aspectRatio: `${imgSize.w}/${imgSize.h}` }}
              >
                {loadingSnapshot && (
                  <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-black/40 text-fg">
                    <Loader2 className="h-6 w-6 animate-spin" />
                  </div>
                )}
                {snapshotError && !loadingSnapshot && (
                  <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center p-4 text-center text-sm text-slate-300">
                    {snapshotError}
                  </div>
                )}
                <canvas
                  ref={canvasRef}
                  width={imgSize.w}
                  height={imgSize.h}
                  onMouseDown={handleMouseDown}
                  onMouseMove={handleMouseMove}
                  onMouseUp={handleMouseUp}
                  onMouseLeave={handleMouseUp}
                  className="h-full w-full cursor-crosshair"
                />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={handleAutoDetect}
                  disabled={detecting || !snapshotUrl}
                  className="dm-btn-secondary !px-3 !py-1.5"
                >
                  {detecting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                  Auto-detect
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setBox(null);
                    setCircleDirty(true);
                  }}
                  className="dm-btn-secondary !px-3 !py-1.5"
                >
                  <XCircle className="h-4 w-4" /> Clear
                </button>
                {circleDirty && hasCircle && <span className="text-xs text-amber-400">unsaved</span>}
              </div>
            </div>

            {/* Step 2: views */}
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-semibold text-slate-200">2. Views</h3>
                <div className="flex gap-2">
                  <button type="button" onClick={resetViews} className="dm-btn-secondary !px-3 !py-1.5">
                    <RotateCcw className="h-4 w-4" /> Default 4 views
                  </button>
                  <button
                    type="button"
                    onClick={addView}
                    disabled={views.length >= MAX_VIEWS}
                    className="dm-btn-secondary !px-3 !py-1.5"
                  >
                    <Plus className="h-4 w-4" /> Add view
                  </button>
                </div>
              </div>
              <p className="mb-2 text-xs text-slate-500">
                <b className="text-slate-400">Direction</b> turns the view around the lens.{" "}
                <b className="text-slate-400">Tilt</b> aims it from straight down (0°) out towards the
                walls (90°). <b className="text-slate-400">Zoom</b> sets how wide it sees.
              </p>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {views.map((v, i) => (
                  <div key={v.key} className="dm-card space-y-2 p-3">
                    <div className="flex items-center gap-2">
                      <span
                        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-black"
                        style={{ background: VIEW_COLORS[i % VIEW_COLORS.length] }}
                      >
                        {i + 1}
                      </span>
                      <input
                        value={v.name}
                        onChange={(e) => updateView(v.key, { name: e.target.value })}
                        placeholder="View name"
                        className="dm-input !py-1.5"
                      />
                      <button
                        type="button"
                        onClick={() => setViews((prev) => prev.filter((x) => x.key !== v.key))}
                        className="text-slate-500 hover:text-red-400"
                        title="Remove this view"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    {cameraId != null && (
                      <ViewPreview cameraId={cameraId} view={v} circle={previewCircle} refreshKey={previewRefresh} />
                    )}
                    <Slider
                      label="Direction"
                      value={v.direction_deg}
                      min={0}
                      max={359}
                      unit="°"
                      onChange={(n) => updateView(v.key, { direction_deg: n })}
                    />
                    <Slider
                      label="Tilt"
                      value={v.tilt_deg}
                      min={0}
                      max={85}
                      unit="°"
                      onChange={(n) => updateView(v.key, { tilt_deg: n })}
                    />
                    <Slider
                      label="Zoom (field of view)"
                      value={v.fov_deg}
                      min={40}
                      max={140}
                      unit="°"
                      hint="lower = zoomed in, higher = wider"
                      onChange={(n) => updateView(v.key, { fov_deg: n })}
                    />
                  </div>
                ))}
              </div>
              {views.length === 0 && (
                <p className="text-sm text-slate-500">
                  No views. Saving now removes any existing views of this camera.
                </p>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <button type="button" onClick={handleSave} disabled={saving} className="dm-btn-primary">
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save views
                </button>
                {saveError && <p className="text-sm text-red-400">{saveError}</p>}
                {savedMessage && <p className="text-sm text-emerald-400">{savedMessage}</p>}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
