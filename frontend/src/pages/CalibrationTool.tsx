import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { CheckCircle2, Loader2, RefreshCw, Ruler, Save, Trash2, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { token } from "../lib/theme";
import type { Calibration, Camera, Point } from "../types";

const HANDLE_RADIUS = 7;
const LINE_COLOR = token("success");

function distance(a: Point, b: Point): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

// Corners must go around the rectangle (same turn direction at every corner);
// a crossed order would give a nonsense ground mapping. Mirrors the backend check.
function isConvexQuad(p: Point[]): boolean {
  if (p.length !== 4) return false;
  const turns = p.map((a, i) => {
    const b = p[(i + 1) % 4];
    const c = p[(i + 2) % 4];
    return Math.sign((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]));
  });
  return turns.every((t) => t !== 0 && t === turns[0]);
}

type Mode = "rect" | "line";

export default function CalibrationTool() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [calibrations, setCalibrations] = useState<Calibration[]>([]);

  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);

  // "rect": 4 ground corners (handles perspective); "line": one reference line
  const [mode, setMode] = useState<Mode>("rect");
  const [line, setLine] = useState<Point[]>([]); // line: 0-2 points, rect: 0-4 corners
  const drawingRef = useRef(false);
  const draggingRef = useRef<number | null>(null);

  const [name, setName] = useState("");
  const [realWorldMeters, setRealWorldMeters] = useState("1.0");
  const [widthMeters, setWidthMeters] = useState("1.0");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    api.get<Camera[]>("/api/cameras").then((res) => {
      setCameras(res.data);
      if (res.data.length > 0) setCameraId(res.data[0].id);
    });
  }, []);

  const loadCalibrations = useCallback((camId: number) => {
    api.get<Calibration[]>(`/api/calibration?camera_id=${camId}`).then((res) => setCalibrations(res.data));
  }, []);

  const loadSnapshot = useCallback((camId: number, attempt = 1) => {
    setLoadingSnapshot(true);
    setSnapshotError(null);
    api
      .get(`/api/camera/snapshot?camera_id=${camId}`, { responseType: "blob" })
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
          setSnapshotError("No frame available yet for this camera. Try again in a moment.");
          setLoadingSnapshot(false);
        }
      });
  }, []);

  useEffect(() => {
    if (cameraId == null) return;
    loadSnapshot(cameraId);
    loadCalibrations(cameraId);
    setLine([]);
  }, [cameraId, loadSnapshot, loadCalibrations]);

  useEffect(() => {
    if (!snapshotUrl) return;
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      draw();
    };
    img.src = snapshotUrl;
  }, [snapshotUrl]);

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

    if (mode === "rect" && line.length > 0) {
      ctx.strokeStyle = LINE_COLOR;
      ctx.lineWidth = 3;
      ctx.beginPath();
      line.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
      if (line.length === 4) {
        ctx.closePath();
        ctx.fillStyle = LINE_COLOR;
        ctx.globalAlpha = 0.15;
        ctx.fill();
        ctx.globalAlpha = 1;
      }
      ctx.stroke();
      line.forEach(([x, y], i) => {
        ctx.beginPath();
        ctx.arc(x, y, HANDLE_RADIUS + 2, 0, Math.PI * 2);
        ctx.fillStyle = i === 0 ? token("accent") : LINE_COLOR;
        ctx.fill();
        ctx.strokeStyle = token("bg");
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = token("bg");
        ctx.font = "bold 11px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(String(i + 1), x, y);
        ctx.textAlign = "start";
        ctx.textBaseline = "alphabetic";
      });
    }

    if (mode === "line" && line.length === 2) {
      ctx.strokeStyle = LINE_COLOR;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(line[0][0], line[0][1]);
      ctx.lineTo(line[1][0], line[1][1]);
      ctx.stroke();

      const mid: Point = [(line[0][0] + line[1][0]) / 2, (line[0][1] + line[1][1]) / 2];
      const d = distance(line[0], line[1]);
      ctx.fillStyle = LINE_COLOR;
      ctx.font = "bold 14px sans-serif";
      ctx.fillText(`${d.toFixed(1)}px`, mid[0] + 8, mid[1] - 8);

      line.forEach(([x, y], i) => {
        ctx.beginPath();
        ctx.arc(x, y, HANDLE_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = i === 0 ? token("accent") : LINE_COLOR;
        ctx.fill();
        ctx.strokeStyle = token("bg");
        ctx.lineWidth = 1.5;
        ctx.stroke();
      });
    }
  }, [line, mode]);

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

  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const p = toImageCoords(e);
    const idx = line.findIndex((pt) => distance(pt, p) <= HANDLE_RADIUS + 2);
    if (idx !== -1 && (mode === "rect" || line.length === 2)) {
      draggingRef.current = idx;
      return;
    }
    if (mode === "rect") {
      // click each corner in turn; once all 4 are placed, only dragging changes them
      if (line.length < 4) setLine((prev) => [...prev, p]);
      return;
    }
    // start a fresh line (click-and-drag)
    setLine([p, p]);
    drawingRef.current = true;
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const p = toImageCoords(e);
    if (drawingRef.current) {
      setLine((prev) => (prev.length === 2 ? [prev[0], p] : prev));
      return;
    }
    if (draggingRef.current !== null) {
      const idx = draggingRef.current;
      setLine((prev) => prev.map((pt, i) => (i === idx ? p : pt)));
    }
  }

  function handleMouseUp() {
    drawingRef.current = false;
    draggingRef.current = null;
  }

  function handleRedraw() {
    setLine([]);
    setSaveError(null);
  }

  function handleModeChange(next: Mode) {
    setMode(next);
    setLine([]);
    setSaveError(null);
  }

  // line: the reference line; rect: side 1->2 (shown for reference only)
  const pixelDistance = line.length >= 2 ? distance(line[0], line[1]) : 0;
  const meters = Number(realWorldMeters) || 0;
  const width = Number(widthMeters) || 0;
  const pixelsPerMeter = meters > 0 ? pixelDistance / meters : 0;
  const rectOk = isConvexQuad(line);

  const shapeOk =
    mode === "rect" ? rectOk && width > 0 : line.length === 2 && pixelDistance > 0;
  const canSave = shapeOk && meters > 0 && name.trim().length > 0 && cameraId != null;

  async function handleSave(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (cameraId == null || !canSave) return;
    setSaveError(null);
    setSaving(true);
    try {
      await api.post("/api/calibration", {
        camera_id: cameraId,
        name,
        line_points: line.map(([x, y]) => [Math.round(x), Math.round(y)]),
        real_world_meters: meters,
        real_world_width_m: mode === "rect" ? width : null,
      });
      setLine([]);
      setName("");
      loadCalibrations(cameraId);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : "Failed to save calibration");
    } finally {
      setSaving(false);
    }
  }

  async function handleActivate(id: number) {
    await api.post(`/api/calibration/${id}/activate`);
    if (cameraId != null) loadCalibrations(cameraId);
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this calibration?")) return;
    await api.delete(`/api/calibration/${id}`);
    if (cameraId != null) loadCalibrations(cameraId);
  }

  return (
    <div className="max-w-6xl">
      <h2 className="text-xl font-semibold text-slate-100">Calibration Tool</h2>
      <p className="mt-1 text-sm text-slate-400">
        Pick a camera, then mark something of known size on the floor. A <b>rectangle</b> (4 corners)
        corrects for perspective, so speeds and distances are right both near and far from the
        camera -- use it for cameras with a long view. A <b>line</b> gives one scale for the whole
        picture, only accurate near where it's drawn.
      </p>

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
        <label className="text-sm">
          <span className="dm-label">Method</span>
          <select
            value={mode}
            onChange={(e) => handleModeChange(e.target.value as Mode)}
            className="dm-input w-56"
          >
            <option value="rect">Rectangle (4 points)</option>
            <option value="line">Line (2 points)</option>
          </select>
        </label>
        <div className="flex items-end">
          <button type="button" onClick={() => cameraId != null && loadSnapshot(cameraId)} className="dm-btn-secondary">
            <RefreshCw className="h-4 w-4" /> Refresh frame
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,960px)_320px]">
        <div>
          <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-slate-900" style={{ aspectRatio: "960/540" }}>
            {loadingSnapshot && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-black/40 text-fg">
                <Loader2 className="h-6 w-6 animate-spin" />
              </div>
            )}
            {snapshotError && !loadingSnapshot && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-sm text-slate-300">
                {snapshotError}
              </div>
            )}
            <canvas
              ref={canvasRef}
              width={960}
              height={540}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
              className="h-full w-full cursor-crosshair"
            />
          </div>
          <p className="mt-2 text-xs text-slate-500">
            {mode === "rect" ? (
              <>
                Click the 4 corners of a rectangle on the floor (e.g. a parking bay, or 4 cones), in order
                around it &middot; drag any corner to fine-tune. The bigger the rectangle, and the more of the
                area you care about it covers, the more accurate.
              </>
            ) : (
              <>Click and drag to draw the reference line &middot; drag either endpoint afterwards to fine-tune it.</>
            )}
          </p>
          <div className="mt-2 flex items-center gap-3">
            <button type="button" onClick={handleRedraw} className="dm-btn-secondary !px-3 !py-1.5">
              <XCircle className="h-4 w-4" /> Redraw
            </button>
            {mode === "line" && line.length === 2 && (
              <span className="text-xs text-slate-500">{pixelDistance.toFixed(1)} px</span>
            )}
            {mode === "rect" && line.length === 4 && !rectOk && (
              <span className="text-xs text-red-400">
                Corners must be clicked in order around the rectangle -- press Redraw and try again.
              </span>
            )}
          </div>

          {calibrations.length > 0 && (
            <div className="dm-card mt-4">
              <div className="border-b border-slate-800 px-4 py-2 text-xs font-medium text-slate-500">
                Saved calibrations for this camera
              </div>
              {calibrations.map((c) => (
                <div key={c.id} className="flex items-center justify-between border-b border-slate-800/60 px-4 py-2 text-sm last:border-0">
                  <div>
                    <span className="text-slate-300">{c.name}</span>
                    <span className="ml-2 text-xs text-slate-500">
                      {c.line_points.length === 4
                        ? `Rectangle ${c.real_world_meters} \u00d7 ${c.real_world_width_m} m (perspective)`
                        : `${c.pixels_per_meter.toFixed(1)} px/m (${c.real_world_meters}m ref)`}
                    </span>
                    {c.is_active && <span className="dm-pill-emerald ml-2">Active</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    {!c.is_active && (
                      <button
                        onClick={() => handleActivate(c.id)}
                        className="text-slate-500 hover:text-emerald-400"
                        title="Set as active calibration"
                      >
                        <CheckCircle2 className="h-4 w-4" />
                      </button>
                    )}
                    <button onClick={() => handleDelete(c.id)} className="text-slate-500 hover:text-red-400">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <form onSubmit={handleSave} className="dm-card space-y-4 p-5">
          <div>
            <span className="dm-label">Calibration name</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Floor stripe near loading bay"
              className="dm-input"
            />
          </div>

          <div>
            <span className="dm-label">
              {mode === "rect" ? <>Side 1 &rarr; 2 length (meters)</> : "Real-world reference distance (meters)"}
            </span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={realWorldMeters}
              onChange={(e) => setRealWorldMeters(e.target.value)}
              className="dm-input"
            />
          </div>

          {mode === "rect" && (
            <div>
              <span className="dm-label">Side 2 &rarr; 3 length (meters)</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                value={widthMeters}
                onChange={(e) => setWidthMeters(e.target.value)}
                className="dm-input"
              />
            </div>
          )}

          <div className="space-y-2 rounded-lg bg-slate-800/40 p-3 text-sm">
            <div className="flex items-center gap-2 text-slate-400">
              <Ruler className="h-4 w-4" />
              <span className="font-medium text-slate-300">Computed values</span>
            </div>
            {mode === "rect" && (
              <div className="flex justify-between text-slate-400">
                <span>Corners placed</span>
                <span className="font-mono text-slate-200">{line.length} / 4</span>
              </div>
            )}
            <div className="flex justify-between text-slate-400">
              <span>{mode === "rect" ? <>Side 1&rarr;2 pixels</> : "Pixel distance (D)"}</span>
              <span className="font-mono text-slate-200">{pixelDistance.toFixed(2)} px</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>{mode === "rect" ? <>PPM along side 1&rarr;2</> : "Pixels per meter (PPM)"}</span>
              <span className="font-mono text-slate-200">{pixelsPerMeter.toFixed(2)} px/m</span>
            </div>
            {!line.length && (
              <p className="text-xs text-slate-500">
                {mode === "rect"
                  ? "Click the corners on the frame to see these update live."
                  : "Draw a line on the frame to see these update live."}
              </p>
            )}
          </div>

          {saveError && <p className="text-sm text-red-400">{saveError}</p>}

          <button type="submit" disabled={!canSave || saving} className="dm-btn-primary w-full justify-center">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save Calibration
          </button>
          {!canSave && (
            <p className="text-center text-xs text-slate-500">
              {mode === "rect"
                ? "Click 4 corners, enter both side lengths and a name to save."
                : "Draw a reference line and enter a name to save."}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
