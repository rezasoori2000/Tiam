import { useCallback, useEffect, useRef, useState } from "react";
import { Filter, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import type { Camera, HeatmapGridResponse, HeatmapOption } from "../types";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

// Formula-based approximation of the classic "jet" colormap (blue -> cyan ->
// green -> yellow -> red) -- matches the reference hot-zone image: red where
// an area is used most, blue where it's used least.
function jetColor(t: number): [number, number, number] {
  const r = Math.round(255 * clamp01(1.5 - Math.abs(4 * t - 3)));
  const g = Math.round(255 * clamp01(1.5 - Math.abs(4 * t - 2)));
  const b = Math.round(255 * clamp01(1.5 - Math.abs(4 * t - 1)));
  return [r, g, b];
}

interface HeatmapViewProps {
  title: string;
  description: string;
  optionsEndpoint: string;
  metricLabel: string;
  buildDataUrl: (params: {
    cameraId: number;
    metric: string;
    startDate: string;
    endDate: string;
  }) => string;
}

export default function HeatmapView({
  title,
  description,
  optionsEndpoint,
  metricLabel,
  buildDataUrl,
}: HeatmapViewProps) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [options, setOptions] = useState<HeatmapOption[]>([]);
  const [metric, setMetric] = useState<string>("");
  const [startDate, setStartDate] = useState(daysAgoIso(7));
  const [endDate, setEndDate] = useState(todayIso());

  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);

  const [gridData, setGridData] = useState<HeatmapGridResponse | null>(null);
  const [filtering, setFiltering] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);

  const [hover, setHover] = useState<{ x: number; y: number; count: number } | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    api.get<Camera[]>("/api/cameras").then((res) => {
      const enabled = res.data.filter((c) => c.is_enabled);
      setCameras(enabled);
      if (enabled.length > 0) setCameraId(enabled[0].id);
    });
    api.get<HeatmapOption[]>(optionsEndpoint).then((res) => {
      setOptions(res.data);
      if (res.data.length > 0) setMetric(res.data[0].value);
    });
  }, [optionsEndpoint]);

  const loadSnapshot = useCallback((camId: number, attempt = 1) => {
    setSnapshotError(null);
    api
      .get(`/api/camera/snapshot?camera_id=${camId}`, { responseType: "blob" })
      .then((res) => {
        const url = URL.createObjectURL(res.data as Blob);
        setSnapshotUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return url;
        });
      })
      .catch(() => {
        if (attempt < 5) {
          setTimeout(() => loadSnapshot(camId, attempt + 1), 1500);
        } else {
          setSnapshotError("No frame available yet for this camera. Try again in a moment.");
        }
      });
  }, []);

  useEffect(() => {
    if (cameraId == null) return;
    loadSnapshot(cameraId);
    setGridData(null);
  }, [cameraId, loadSnapshot]);

  useEffect(() => {
    if (!snapshotUrl) return;
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
      }
      draw();
    };
    img.src = snapshotUrl;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshotUrl]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imageRef.current;
    if (!canvas || !img) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    if (!gridData || gridData.max_count <= 0) return;

    const { rows, cols, grid, max_count } = gridData;
    const cellCanvas = document.createElement("canvas");
    cellCanvas.width = cols;
    cellCanvas.height = rows;
    const cellCtx = cellCanvas.getContext("2d");
    if (!cellCtx) return;
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const count = grid[row][col];
        if (count <= 0) continue;
        const t = clamp01(count / max_count);
        const [r, g, b] = jetColor(t);
        const alpha = clamp01(0.25 + 0.65 * t);
        cellCtx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        cellCtx.fillRect(col, row, 1, 1);
      }
    }

    ctx.save();
    ctx.filter = "blur(10px)";
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(cellCanvas, 0, 0, cols, rows, 0, 0, canvas.width, canvas.height);
    ctx.restore();
  }, [gridData]);

  useEffect(() => {
    draw();
  }, [draw]);

  async function handleFilter() {
    if (cameraId == null || !metric) return;
    setFiltering(true);
    setFilterError(null);
    try {
      const url = buildDataUrl({ cameraId, metric, startDate, endDate });
      const res = await api.get<HeatmapGridResponse>(url);
      setGridData(res.data);
    } catch {
      setFilterError("Could not load heatmap data for that selection.");
    } finally {
      setFiltering(false);
    }
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!gridData) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const px = (e.clientX - rect.left) * scaleX;
    const py = (e.clientY - rect.top) * scaleY;
    const col = Math.min(Math.floor((px / canvas.width) * gridData.cols), gridData.cols - 1);
    const row = Math.min(Math.floor((py / canvas.height) * gridData.rows), gridData.rows - 1);
    if (row < 0 || col < 0) return;
    setHover({ x: e.clientX - rect.left, y: e.clientY - rect.top, count: gridData.grid[row][col] });
  }

  const selectedCamera = cameras.find((c) => c.id === cameraId);

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">{title}</h2>
        <p className="mt-1 text-sm text-slate-400">{description}</p>
      </div>

      <div className="dm-card grid grid-cols-1 gap-3 p-4 sm:grid-cols-5">
        <label className="text-sm">
          <span className="dm-label">Camera</span>
          <select
            value={cameraId ?? ""}
            onChange={(e) => setCameraId(Number(e.target.value))}
            className="dm-input"
          >
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          <span className="dm-label">{metricLabel}</span>
          <select value={metric} onChange={(e) => setMetric(e.target.value)} className="dm-input">
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          <span className="dm-label">Start date</span>
          <input
            type="date"
            value={startDate}
            max={endDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="dm-input"
          />
        </label>

        <label className="text-sm">
          <span className="dm-label">End date</span>
          <input
            type="date"
            value={endDate}
            min={startDate}
            max={todayIso()}
            onChange={(e) => setEndDate(e.target.value)}
            className="dm-input"
          />
        </label>

        <div className="flex items-end">
          <button
            onClick={handleFilter}
            disabled={cameraId == null || !metric || filtering}
            className="dm-btn-primary w-full justify-center"
          >
            {filtering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Filter className="h-4 w-4" />}
            Filter
          </button>
        </div>
      </div>

      {filterError && <p className="text-sm text-red-400">{filterError}</p>}

      <div className="dm-card overflow-hidden p-4">
        <div className="relative mx-auto w-fit max-w-full">
          {snapshotError ? (
            <p className="p-6 text-sm text-slate-400">{snapshotError}</p>
          ) : (
            <canvas
              ref={canvasRef}
              onMouseMove={handleMouseMove}
              onMouseLeave={() => setHover(null)}
              className="max-w-full rounded-lg border border-slate-800"
            />
          )}
          {hover && (
            <div
              className="pointer-events-none absolute rounded-md border border-slate-700 bg-apl-midnight/95 px-2 py-1 text-xs text-slate-100 shadow-lg"
              style={{ left: hover.x + 12, top: hover.y + 12 }}
            >
              {hover.count} {hover.count === 1 ? "sample" : "samples"}
            </div>
          )}
        </div>

        {gridData && (
          <div className="mt-4 flex items-center gap-3">
            <span className="text-xs text-slate-400">Low</span>
            <div
              className="h-2.5 flex-1 rounded-full"
              style={{
                background:
                  "linear-gradient(to right, rgb(0,0,255), rgb(0,255,255), rgb(0,255,0), rgb(255,255,0), rgb(255,0,0))",
              }}
            />
            <span className="text-xs text-slate-400">High</span>
            <span className="ml-2 text-xs text-slate-500">max {gridData.max_count}</span>
          </div>
        )}

        {!gridData && !filterError && (
          <p className="mt-3 text-xs text-slate-500">
            {selectedCamera ? `Showing ${selectedCamera.name}'s live view. ` : ""}
            Choose a {metricLabel.toLowerCase()} and date range, then click Filter to see its hot zone.
          </p>
        )}
      </div>
    </div>
  );
}
