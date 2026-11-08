import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Crop, Loader2, Pencil, RefreshCw, Save, Trash2, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { token } from "../lib/theme";
import type { AppliesTo, Camera, Point, Zone, ZoneCreatePayload, ZoneType } from "../types";

const HIT_RADIUS = 9; // image-space px for point hit-testing (click/drag/delete)
const DRAFT_ZONE_COLOR = "rgba(16, 185, 129, 0.95)"; // emerald-500

// One distinct colour per existing zone (cycled by list position), so
// overlapping/nearby zones on the same camera are easy to tell apart both in
// the "Existing zones" list and drawn on the canvas.
const ZONE_COLOR_PALETTE = [
  "rgba(248, 113, 113, 0.95)", // red-400
  "rgba(96, 165, 250, 0.95)", // blue-400
  "rgba(250, 204, 21, 0.95)", // yellow-400
  "rgba(232, 121, 249, 0.95)", // fuchsia-400
  "rgba(45, 212, 191, 0.95)", // teal-400
  "rgba(251, 146, 60, 0.95)", // orange-400
  "rgba(167, 139, 250, 0.95)", // violet-400
  "rgba(148, 163, 184, 0.95)", // slate-400
];

function zoneColor(index: number): string {
  return ZONE_COLOR_PALETTE[index % ZONE_COLOR_PALETTE.length];
}

interface RuleFormState {
  applies_to: AppliesTo;
  rule_exclusion: boolean;
  max_speed_kmh: string;
  rule_stop_required: boolean;
  stop_min_seconds: string;
  rule_prowling: boolean;
  prowling_min_vehicles: string;
  rule_fight: boolean;
  fight_min_seconds: string;
  time_restriction_enabled: boolean;
  from_time: string;
  to_time: string;
}

function rulesFromType(zt: ZoneType | undefined): RuleFormState {
  if (!zt) {
    return {
      applies_to: "person", rule_exclusion: false,
      max_speed_kmh: "",
      rule_stop_required: false, stop_min_seconds: "1",
      rule_prowling: false, prowling_min_vehicles: "3",
      rule_fight: false, fight_min_seconds: "2",
      time_restriction_enabled: false, from_time: "", to_time: "",
    };
  }
  return {
    applies_to: zt.applies_to,
    rule_exclusion: zt.rule_exclusion,
    max_speed_kmh: zt.default_max_speed_kmh != null ? String(zt.default_max_speed_kmh) : "",
    rule_stop_required: zt.rule_stop_required,
    stop_min_seconds: String(zt.default_stop_min_seconds),
    rule_prowling: zt.rule_prowling,
    prowling_min_vehicles: String(zt.default_prowling_min_vehicles),
    rule_fight: zt.rule_fight,
    fight_min_seconds: String(zt.default_fight_min_seconds),
    time_restriction_enabled: zt.time_restriction_enabled,
    from_time: zt.default_from_time ?? "",
    to_time: zt.default_to_time ?? "",
  };
}

function rulesFromZone(z: Zone): RuleFormState {
  return {
    applies_to: z.applies_to,
    rule_exclusion: z.rule_exclusion,
    max_speed_kmh: z.max_speed_kmh != null ? String(z.max_speed_kmh) : "",
    rule_stop_required: z.rule_stop_required,
    stop_min_seconds: String(z.stop_min_seconds),
    rule_prowling: z.rule_prowling,
    prowling_min_vehicles: String(z.prowling_min_vehicles),
    rule_fight: z.rule_fight,
    fight_min_seconds: String(z.fight_min_seconds),
    time_restriction_enabled: z.time_restriction_enabled,
    from_time: z.from_time ?? "",
    to_time: z.to_time ?? "",
  };
}

function distance(a: Point, b: Point): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1]);
}

export default function ZoneStudio() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [zoneTypes, setZoneTypes] = useState<ZoneType[]>([]);
  const [zoneTypeId, setZoneTypeId] = useState<number | null>(null);
  const [existingZones, setExistingZones] = useState<Zone[]>([]);

  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [snapshotError, setSnapshotError] = useState<string | null>(null);
  const [loadingSnapshot, setLoadingSnapshot] = useState(false);

  const [points, setPoints] = useState<Point[]>([]);
  const [closed, setClosed] = useState(false);
  const draggingRef = useRef<number | null>(null);

  const [name, setName] = useState("");
  const [rules, setRules] = useState<RuleFormState>(rulesFromType(undefined));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restrictingZoneId, setRestrictingZoneId] = useState<number | null>(null);
  // Zone highlighted by clicking its row in "Existing zones" (canvas emphasis only).
  const [selectedZoneId, setSelectedZoneId] = useState<number | null>(null);
  // Set while the right-hand form is editing an existing zone's rules
  // (instead of drawing/saving a brand new one) -- PUT, not POST, on submit.
  const [editingZoneId, setEditingZoneId] = useState<number | null>(null);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);

  // ---- load cameras + zone types once ----
  useEffect(() => {
    api.get<Camera[]>("/api/cameras").then((res) => {
      setCameras(res.data);
      if (res.data.length > 0) setCameraId(res.data[0].id);
    });
    api.get<ZoneType[]>("/api/zone-types").then((res) => {
      setZoneTypes(res.data);
      if (res.data.length > 0) setZoneTypeId(res.data[0].id);
    });
  }, []);

  const loadZonesForCamera = useCallback((camId: number) => {
    api.get<Zone[]>(`/api/zones?camera_id=${camId}`).then((res) => setExistingZones(res.data));
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
        // The camera worker may not have produced its first frame yet (or is
        // mid-reconnect) -- retry a few times before surfacing an error.
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
    loadZonesForCamera(cameraId);
    setPoints([]);
    setClosed(false);
    setSelectedZoneId(null);
    setEditingZoneId(null);
  }, [cameraId, loadSnapshot, loadZonesForCamera]);

  useEffect(() => {
    if (editingZoneId != null) return; // editing an existing zone's own values -- don't overwrite them
    const zt = zoneTypes.find((z) => z.id === zoneTypeId);
    setRules(rulesFromType(zt));
  }, [zoneTypeId, zoneTypes, editingZoneId]);

  // ---- load the snapshot image element whenever its URL changes ----
  useEffect(() => {
    if (!snapshotUrl) return;
    const img = new Image();
    img.onload = () => {
      imageRef.current = img;
      draw();
    };
    img.src = snapshotUrl;
  }, [snapshotUrl]);

  // ---- drawing ----
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

    existingZones.forEach((zone, i) => {
      const color = zoneColor(i);
      const isSelected = zone.id === selectedZoneId;
      drawPolygon(ctx, zone.polygon_points, color, false, false, isSelected);
      const [lx, ly] = zone.polygon_points[0];
      ctx.fillStyle = color;
      ctx.font = isSelected ? "bold 13px sans-serif" : "13px sans-serif";
      ctx.fillText(zone.name, lx + 4, Math.max(ly - 6, 12));
    });

    if (points.length > 0) {
      drawPolygon(ctx, points, DRAFT_ZONE_COLOR, closed, true);
    }
  }, [points, closed, existingZones, selectedZoneId]);

  function drawPolygon(
    ctx: CanvasRenderingContext2D, pts: Point[], color: string, isClosed: boolean,
    withHandles = false, highlighted = false
  ) {
    ctx.strokeStyle = color;
    ctx.lineWidth = highlighted ? 4 : 2;
    ctx.fillStyle = color.replace(/[\d.]+\)$/, highlighted ? "0.3)" : "0.15)");

    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    if (isClosed || highlighted) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();

    if (withHandles) {
      pts.forEach(([x, y], i) => {
        ctx.beginPath();
        ctx.arc(x, y, i === 0 ? 6 : 5, 0, Math.PI * 2);
        ctx.fillStyle = i === 0 ? token("accent") : color;
        ctx.fill();
        ctx.strokeStyle = token("bg");
        ctx.lineWidth = 1;
        ctx.stroke();
      });
    }
  }

  useEffect(() => {
    draw();
  }, [draw]);

  // ---- mouse interaction (image-space coordinates) ----
  function toImageCoords(e: React.MouseEvent<HTMLCanvasElement>): Point {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return [(e.clientX - rect.left) * scaleX, (e.clientY - rect.top) * scaleY];
  }

  function findNearbyPointIndex(p: Point): number {
    return points.findIndex((pt) => distance(pt, p) <= HIT_RADIUS);
  }

  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const p = toImageCoords(e);
    const idx = findNearbyPointIndex(p);
    if (idx !== -1) {
      if (idx === 0 && points.length >= 3 && !closed) {
        setClosed(true);
        return;
      }
      draggingRef.current = idx;
      return;
    }
    if (closed) return; // shape finalized; delete/drag to modify, or start a new zone
    setPoints((prev) => [...prev, p]);
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (draggingRef.current === null) return;
    const p = toImageCoords(e);
    const idx = draggingRef.current;
    setPoints((prev) => prev.map((pt, i) => (i === idx ? p : pt)));
  }

  function handleMouseUp() {
    draggingRef.current = null;
  }

  function handleContextMenu(e: React.MouseEvent<HTMLCanvasElement>) {
    e.preventDefault();
    const p = toImageCoords(e);
    const idx = findNearbyPointIndex(p);
    if (idx === -1) return;
    setPoints((prev) => prev.filter((_, i) => i !== idx));
    if (points.length - 1 < 3) setClosed(false);
  }

  function handleNewZone() {
    setPoints([]);
    setClosed(false);
    setName("");
    setSaveError(null);
    setEditingZoneId(null);
    setRules(rulesFromType(zoneTypes.find((zt) => zt.id === zoneTypeId)));
  }

  function openEditZone(zone: Zone) {
    setEditingZoneId(zone.id);
    setSelectedZoneId(zone.id);
    setPoints([]);
    setClosed(false);
    setSaveError(null);
    setName(zone.name);
    setRules(rulesFromZone(zone));
  }

  const selectedZoneType = useMemo(
    () => zoneTypes.find((z) => z.id === zoneTypeId),
    [zoneTypes, zoneTypeId]
  );

  function rulesPayload() {
    return {
      applies_to: rules.applies_to,
      rule_exclusion: rules.rule_exclusion,
      max_speed_kmh: rules.max_speed_kmh ? Number(rules.max_speed_kmh) : null,
      rule_stop_required: rules.rule_stop_required,
      stop_min_seconds: Number(rules.stop_min_seconds) || 1,
      rule_prowling: rules.rule_prowling,
      prowling_min_vehicles: Number(rules.prowling_min_vehicles) || 3,
      rule_fight: rules.rule_fight,
      fight_min_seconds: Number(rules.fight_min_seconds) || 2,
      time_restriction_enabled: rules.time_restriction_enabled,
      from_time: rules.time_restriction_enabled ? rules.from_time || null : null,
      to_time: rules.time_restriction_enabled ? rules.to_time || null : null,
    };
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (cameraId == null) return;
    setSaveError(null);
    setSaving(true);
    try {
      if (editingZoneId != null) {
        await api.put(`/api/zones/${editingZoneId}`, { name, ...rulesPayload() });
      } else {
        if (zoneTypeId == null) return;
        const payload: ZoneCreatePayload = {
          camera_id: cameraId,
          zone_type_id: zoneTypeId,
          name,
          polygon_points: points.map(([x, y]) => [Math.round(x), Math.round(y)]),
          ...rulesPayload(),
        };
        await api.post("/api/zones", payload);
      }
      handleNewZone();
      loadZonesForCamera(cameraId);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setSaveError(typeof detail === "string" ? detail : "Failed to save zone");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteZone(id: number) {
    if (!confirm("Delete this zone?")) return;
    await api.delete(`/api/zones/${id}`);
    if (selectedZoneId === id) setSelectedZoneId(null);
    if (editingZoneId === id) handleNewZone();
    if (cameraId != null) loadZonesForCamera(cameraId);
  }

  const selectedCamera = cameras.find((c) => c.id === cameraId) ?? null;

  async function handleToggleRestriction(zoneId: number) {
    if (cameraId == null) return;
    const clearing = selectedCamera?.restricted_zone_id === zoneId;
    setRestrictingZoneId(zoneId);
    try {
      const res = await api.put<Camera>(`/api/cameras/${cameraId}`, {
        restricted_zone_id: clearing ? null : zoneId,
      });
      setCameras((prev) => prev.map((c) => (c.id === cameraId ? res.data : c)));
    } finally {
      setRestrictingZoneId(null);
    }
  }

  const canSave = editingZoneId != null
    ? name.trim().length > 0
    : points.length >= 3 && name.trim().length > 0 && cameraId != null && zoneTypeId != null;

  return (
    <div className="max-w-6xl">
      <h2 className="text-xl font-semibold text-slate-100">Zone Studio</h2>
      <p className="mt-1 text-sm text-slate-400">
        Pick a camera, draw a polygon on its live frame, choose what kind of hazard it should
        detect, then save.
      </p>

      <div className="mt-4 flex flex-wrap gap-3">
        <label className="text-sm">
          <span className="dm-label">1. Camera</span>
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
              onContextMenu={handleContextMenu}
              className="h-full w-full cursor-crosshair"
            />
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Click to add a point &middot; drag a point to move it &middot; click the first
            (yellow) point once you have 3+ points to close the shape &middot; right-click a
            point to delete it.
          </p>
          <div className="mt-2 flex items-center gap-3">
            <button type="button" onClick={handleNewZone} className="dm-btn-secondary !px-3 !py-1.5">
              <XCircle className="h-4 w-4" /> New Zone
            </button>
            <span className="text-xs text-slate-500">{points.length} point(s){closed ? " · closed" : ""}</span>
          </div>

          {existingZones.length > 0 && (
            <div className="dm-card mt-4">
              <div className="border-b border-slate-800 px-4 py-2 text-xs font-medium text-slate-500">
                Existing zones on this camera
              </div>
              {existingZones.map((z, i) => {
                const isRestricted = selectedCamera?.restricted_zone_id === z.id;
                const isSelected = z.id === selectedZoneId;
                const color = zoneColor(i);
                return (
                <div
                  key={z.id}
                  onClick={() => setSelectedZoneId((prev) => (prev === z.id ? null : z.id))}
                  title="Click to highlight this zone on the image"
                  className={`flex cursor-pointer items-center justify-between border-b px-4 py-2 text-sm last:border-0 ${
                    isSelected ? "border-slate-700 bg-slate-800/60" : "border-slate-800/60"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="h-3 w-3 shrink-0 rounded-full"
                      style={{ backgroundColor: color, boxShadow: `0 0 0 1px rgba(0,0,0,0.4)` }}
                    />
                    <span className="text-slate-300">{z.name}</span>
                    {isRestricted && <span className="dm-pill-emerald">Zone-only view</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={(e) => { e.stopPropagation(); openEditZone(z); }}
                      title="Edit this zone's rules"
                      className="text-slate-500 hover:text-apl-sunset"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleToggleRestriction(z.id); }}
                      disabled={restrictingZoneId === z.id}
                      title={
                        isRestricted
                          ? "Show the full camera view again"
                          : "Restrict this camera's view + detection to only this zone"
                      }
                      className={
                        isRestricted
                          ? "text-apl-sunset hover:text-apl-sunset/70 disabled:opacity-50"
                          : "text-slate-500 hover:text-apl-sunset disabled:opacity-50"
                      }
                    >
                      {restrictingZoneId === z.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Crop className="h-4 w-4" />
                      )}
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteZone(z.id); }}
                      className="text-slate-500 hover:text-red-400"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
                );
              })}
            </div>
          )}
        </div>

        <form onSubmit={handleSubmit} className="dm-card space-y-4 p-5">
          {editingZoneId != null && (
            <div className="flex items-center justify-between rounded-lg bg-slate-800/60 px-3 py-2 text-xs text-slate-300">
              <span>Editing existing zone -- shape unchanged, rules only</span>
              <button type="button" onClick={handleNewZone} className="text-apl-sunset hover:underline">
                Cancel
              </button>
            </div>
          )}

          <div>
            <span className="dm-label">2. Zone name</span>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Loading Bay Exclusion"
              className="dm-input"
            />
          </div>

          {editingZoneId == null && (
            <div>
              <span className="dm-label">3. Zone type (hazard)</span>
              <select
                value={zoneTypeId ?? ""}
                onChange={(e) => setZoneTypeId(Number(e.target.value))}
                className="dm-input"
              >
                {zoneTypes.map((zt) => (
                  <option key={zt.id} value={zt.id}>{zt.name}</option>
                ))}
              </select>
              {selectedZoneType?.description && (
                <p className="mt-1 text-xs text-slate-500">{selectedZoneType.description}</p>
              )}
            </div>
          )}

          <div className="space-y-2 rounded-lg bg-slate-800/40 p-3">
            <p className="text-xs font-medium text-slate-400">
              {editingZoneId != null
                ? "Rules for this zone -- adjust and save"
                : "Rules (pre-filled from the zone type -- adjust if needed for this specific zone)"}
            </p>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={rules.rule_exclusion}
                onChange={(e) => setRules((r) => ({ ...r, rule_exclusion: e.target.checked }))}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
              />
              Enable exclusion ({rules.applies_to})
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={rules.rule_stop_required}
                onChange={(e) =>
                  setRules((r) => ({ ...r, rule_stop_required: e.target.checked }))
                }
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
              />
              Require stop (e.g. stop sign)
            </label>
            {rules.rule_stop_required && (
              <label className="ml-6 block text-sm">
                <span className="mb-1 block text-slate-400">Min stop duration (s)</span>
                <input
                  type="number" step="0.5"
                  value={rules.stop_min_seconds}
                  onChange={(e) => setRules((r) => ({ ...r, stop_min_seconds: e.target.value }))}
                  className="dm-input w-32 !py-1.5"
                />
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={rules.rule_prowling}
                onChange={(e) => setRules((r) => ({ ...r, rule_prowling: e.target.checked }))}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
              />
              Car prowling (person going car to car)
            </label>
            {rules.rule_prowling && (
              <label className="ml-6 block text-sm">
                <span className="mb-1 block text-slate-400">Alert at score (cars checked)</span>
                <input
                  type="number" min="1" max="20" step="0.5"
                  value={rules.prowling_min_vehicles}
                  onChange={(e) => setRules((r) => ({ ...r, prowling_min_vehicles: e.target.value }))}
                  className="dm-input w-32 !py-1.5"
                />
                <span className="mt-1 block text-xs text-muted">Alerts when a person here checks several parked cars, lingers 10 s+ beside one (+0.5) or crouches beside one (+1). Each different car = 1 point. Needs the camera calibrated.</span>
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={rules.rule_fight}
                onChange={(e) => setRules((r) => ({ ...r, rule_fight: e.target.checked }))}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
              />
              Fight / assault
            </label>
            {rules.rule_fight && (
              <label className="ml-6 block text-sm">
                <span className="mb-1 block text-slate-400">Alert after (seconds of fighting)</span>
                <input
                  type="number" min="0.5" max="10" step="0.5"
                  value={rules.fight_min_seconds}
                  onChange={(e) => setRules((r) => ({ ...r, fight_min_seconds: e.target.value }))}
                  className="dm-input w-32 !py-1.5"
                />
                <span className="mt-1 block text-xs text-muted">Alerts when two people here are close together with fast punching/kicking movement for this long, or one rushes at or knocks down the other. Needs the camera calibrated.</span>
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={rules.max_speed_kmh !== ""}
                onChange={(e) => setRules((r) => ({ ...r, max_speed_kmh: e.target.checked ? (r.max_speed_kmh || "10") : "" }))}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
              />
              Speed limit check
            </label>
            {rules.max_speed_kmh !== "" && (
              <label className="ml-6 block text-sm">
                <span className="mb-1 block text-slate-400">Max speed (km/h)</span>
                <input
                  type="number"
                  value={rules.max_speed_kmh}
                  onChange={(e) => setRules((r) => ({ ...r, max_speed_kmh: e.target.value }))}
                  className="dm-input w-32 !py-1.5"
                />
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={rules.time_restriction_enabled}
                onChange={(e) => setRules((r) => ({ ...r, time_restriction_enabled: e.target.checked }))}
                className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
              />
              Restrict to a time window
            </label>
            {rules.time_restriction_enabled && (
              <div className="ml-6 flex gap-3">
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-400">From time</span>
                  <input
                    type="time"
                    value={rules.from_time}
                    onChange={(e) => setRules((r) => ({ ...r, from_time: e.target.value }))}
                    className="dm-input w-32 !py-1.5"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block text-slate-400">To time</span>
                  <input
                    type="time"
                    value={rules.to_time}
                    onChange={(e) => setRules((r) => ({ ...r, to_time: e.target.value }))}
                    className="dm-input w-32 !py-1.5"
                  />
                </label>
              </div>
            )}
          </div>

          {saveError && <p className="text-sm text-red-400">{saveError}</p>}

          <button type="submit" disabled={!canSave || saving} className="dm-btn-primary w-full justify-center">
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {editingZoneId != null ? "Save Changes" : "Save Zone"}
          </button>
          {!canSave && (
            <p className="text-center text-xs text-slate-500">
              {editingZoneId != null
                ? "Enter a name to save."
                : "Draw a polygon (3+ points) and enter a name to save."}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}
