import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Aperture, LayoutGrid, Loader2, Pause, Pencil, Play, Plus, RotateCw, Save, Settings2, Trash2, Video, Wifi, X } from "lucide-react";
import { api } from "../lib/api";
import type {
  Camera,
  CameraCreatePayload,
  CameraProtocol,
  CameraStatus,
  CameraStatusResponse,
} from "../types";

const STATUS_STYLES: Record<CameraStatus, string> = {
  connected: "dm-pill-emerald",
  starting: "dm-pill-amber",
  reconnecting: "dm-pill-amber",
  stopped: "dm-pill-slate",
  error: "dm-pill-red",
};

function StatusPill({ status }: { status: CameraStatus }) {
  return <span className={STATUS_STYLES[status]}>{status}</span>;
}

function cameraAddress(camera: Camera, cameras: Camera[]): string {
  if (camera.source_type === "fisheye_view") {
    const parent = cameras.find((c) => c.id === camera.fisheye_parent_id);
    return `View of fisheye camera "${parent?.name ?? camera.fisheye_parent_id}"`;
  }
  if (camera.source_type === "webcam") {
    return `Server webcam #${camera.device_index ?? 0}`;
  }
  const auth = camera.username ? `${camera.username}@` : "";
  return `${camera.protocol}://${auth}${camera.ip}:${camera.port}${camera.stream_path ?? ""}`;
}

type Compression = "h264" | "h265" | "jpeg";
type SourceType = "ip" | "webcam" | "quad" | "fisheye";

interface FormState {
  name: string;
  source_type: SourceType;
  protocol: CameraProtocol;
  ip: string;
  port: string;
  compression: Compression;
  stream_path: string;
  username: string;
  password: string;
  device_index: string;
  // one name/enabled flag per lens, only used when source_type === "quad"
  quadNames: [string, string, string, string];
  quadEnabled: [boolean, boolean, boolean, boolean];
}

const INITIAL_FORM: FormState = {
  name: "",
  source_type: "ip",
  protocol: "rtsp",
  ip: "",
  port: "554",
  compression: "h265",
  stream_path: "",
  username: "",
  password: "",
  device_index: "0",
  quadNames: ["", "", "", ""],
  quadEnabled: [true, true, true, true],
};

function suggestedStreamPath(compression: Compression): string {
  return `/MediaInput/${compression}/stream_1`;
}

// Fills the form from an existing camera for editing. The password is
// never returned by the API, so it starts blank ("leave blank to keep").
function formFromCamera(camera: Camera): FormState {
  const compression = camera.stream_path?.match(/\/MediaInput\/(h264|h265|jpeg)\b/)?.[1] as
    | Compression
    | undefined;
  return {
    ...INITIAL_FORM,
    name: camera.name,
    source_type:
      camera.source_type === "webcam"
        ? "webcam"
        : camera.source_type === "fisheye" || camera.source_type === "fisheye_view"
          ? "fisheye"
          : "ip",
    protocol: camera.protocol ?? "rtsp",
    ip: camera.ip ?? "",
    port: camera.port != null ? String(camera.port) : "554",
    compression: compression ?? INITIAL_FORM.compression,
    stream_path: camera.stream_path ?? "",
    username: camera.username ?? "",
    password: "",
    device_index: String(camera.device_index ?? 0),
  };
}

// Verified against a real i-PRO WV-X8570 4-lens camera: each lens is a
// separate RTSP source at the same IP/port, distinguished by a "ch_N" suffix
// -- confirmed by capturing and visually comparing a frame from each channel.
function quadLensStreamPath(lens: number): string {
  return `/MediaInput/WS/stream_1/ch_${lens}`;
}

export default function Cameras() {
  const navigate = useNavigate();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [statuses, setStatuses] = useState<Record<number, CameraStatusResponse>>({});
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restartingId, setRestartingId] = useState<number | null>(null);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  // Camera currently loaded into the form for editing (null = adding a new one).
  const [editing, setEditing] = useState<Camera | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const loadCameras = useCallback(async () => {
    const res = await api.get<Camera[]>("/api/cameras");
    setCameras(res.data);
    setLoading(false);
  }, []);

  const loadStatuses = useCallback(async (list: Camera[]) => {
    const entries = await Promise.all(
      list.map(async (cam) => {
        try {
          const res = await api.get<CameraStatusResponse>(`/api/cameras/${cam.id}/status`);
          return [cam.id, res.data] as const;
        } catch {
          return [cam.id, { status: "error" as CameraStatus, last_error: "status unavailable" }] as const;
        }
      })
    );
    setStatuses(Object.fromEntries(entries));
  }, []);

  useEffect(() => {
    loadCameras();
  }, [loadCameras]);

  useEffect(() => {
    if (cameras.length === 0) return;
    loadStatuses(cameras);
    const interval = setInterval(() => loadStatuses(cameras), 5000);
    return () => clearInterval(interval);
  }, [cameras, loadStatuses]);

  function extractErrorMessage(err: any): string {
    const detail = err?.response?.data?.detail;
    return typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: any) => d.msg).join("; ")
        : editing
          ? "Failed to save camera"
          : "Failed to create camera";
  }

  function startEdit(camera: Camera) {
    setEditing(camera);
    setForm(formFromCamera(camera));
    setError(null);
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function cancelEdit() {
    setEditing(null);
    setForm(INITIAL_FORM);
    setError(null);
  }

  async function saveEdit(camera: Camera) {
    // Only the fields this camera type actually has; source type can't be
    // changed (the API's CameraUpdate doesn't accept it).
    const payload: Record<string, unknown> = { name: form.name.trim() };
    if (camera.source_type === "webcam") {
      payload.device_index = Number(form.device_index) || 0;
    } else if (camera.source_type === "ip" || camera.source_type === "fisheye") {
      payload.protocol = form.protocol;
      payload.ip = form.ip.trim();
      payload.port = Number(form.port);
      payload.stream_path = form.stream_path.trim() || null;
      payload.username = form.username.trim() || null;
      if (form.password) payload.password = form.password;
    }
    await api.put(`/api/cameras/${camera.id}`, payload);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (editing) {
        await saveEdit(editing);
        setEditing(null);
        setForm(INITIAL_FORM);
        await loadCameras();
        return;
      }
      if (form.source_type === "quad") {
        const selectedLenses = [1, 2, 3, 4].filter((lens) => form.quadEnabled[lens - 1]);
        if (selectedLenses.length === 0) {
          throw new Error("Select at least one lens to add.");
        }
        let created = 0;
        for (const lens of selectedLenses) {
          const lensName = form.quadNames[lens - 1].trim();
          const payload: CameraCreatePayload = {
            name: lensName,
            source_type: "ip",
            protocol: form.protocol,
            ip: form.ip,
            port: Number(form.port),
            stream_path: quadLensStreamPath(lens),
            username: form.username || null,
            password: form.password || null,
          };
          try {
            await api.post("/api/cameras", payload);
            created++;
          } catch (err: any) {
            throw new Error(
              `Created ${created} of ${selectedLenses.length} selected lenses, then failed on "${lensName}": ${extractErrorMessage(err)}`
            );
          }
        }
      } else {
        const payload: CameraCreatePayload =
          form.source_type === "webcam"
            ? {
                name: form.name,
                source_type: "webcam",
                device_index: Number(form.device_index) || 0,
              }
            : {
                name: form.name,
                source_type: form.source_type === "fisheye" ? "fisheye" : "ip",
                protocol: form.protocol,
                ip: form.ip,
                port: Number(form.port),
                stream_path: form.stream_path || null,
                username: form.username || null,
                password: form.password || null,
              };
        const res = await api.post<Camera>("/api/cameras", payload);
        if (form.source_type === "fisheye") {
          setForm(INITIAL_FORM);
          navigate(`/admin/fisheye?camera=${res.data.id}`);
          return;
        }
      }
      setForm(INITIAL_FORM);
      await loadCameras();
    } catch (err: any) {
      setError(err instanceof Error ? err.message : extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    const viewCount = cameras.filter((c) => c.fisheye_parent_id === id).length;
    const message =
      viewCount > 0
        ? `Remove this fisheye camera and its ${viewCount} view(s)?`
        : "Remove this camera? Its zones and calibration will remain but be orphaned.";
    if (!confirm(message)) return;
    await api.delete(`/api/cameras/${id}`);
    if (editing && (editing.id === id || editing.fisheye_parent_id === id)) cancelEdit();
    await loadCameras();
  }

  async function handleToggleEnabled(camera: Camera) {
    setTogglingId(camera.id);
    try {
      await api.put(`/api/cameras/${camera.id}`, { is_enabled: !camera.is_enabled });
      await loadCameras();
    } finally {
      setTogglingId(null);
    }
  }

  async function handleRestart(id: number) {
    setRestartingId(id);
    try {
      await api.post(`/api/cameras/${id}/restart`);
      await loadStatuses(cameras);
    } finally {
      setRestartingId(null);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">Cameras</h2>
        <p className="mt-1 text-sm text-slate-400">
          Register IP cameras or this server's webcam. Each runs its own detection
          pipeline with its own zones and calibration.
        </p>
      </div>

      <form
        ref={formRef}
        onSubmit={handleSubmit}
        className={`dm-card scroll-mt-4 space-y-4 p-5 ${editing ? "!border-apl-sunset" : ""}`}
      >
        {editing && (
          <div className="flex items-center justify-between gap-3 rounded-lg bg-apl-sunset/10 px-3 py-2 text-sm">
            <span className="text-apl-sunset">
              Editing <strong>{editing.name}</strong>
              {editing.source_type === "fisheye_view" && " (fisheye view: only the name can be changed here)"}
            </span>
            <button type="button" onClick={cancelEdit} className="text-slate-400 hover:text-slate-200" title="Cancel editing">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {(["ip", "quad", "fisheye", "webcam"] as const).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setForm((f) => ({ ...f, source_type: type }))}
              // A camera's type can't be changed once it exists.
              disabled={editing != null && form.source_type !== type}
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-30 ${
                form.source_type === type
                  ? "border-apl-sunset bg-apl-sunset/10 text-apl-sunset"
                  : "border-slate-700 text-slate-400 hover:bg-slate-800"
              }`}
            >
              {type === "ip" && <Wifi className="h-4 w-4" />}
              {type === "quad" && <LayoutGrid className="h-4 w-4" />}
              {type === "fisheye" && <Aperture className="h-4 w-4" />}
              {type === "webcam" && <Video className="h-4 w-4" />}
              {type === "ip"
                ? "IP Camera"
                : type === "quad"
                  ? "4-Lens Camera"
                  : type === "fisheye"
                    ? "Fisheye Camera"
                    : "Server Webcam"}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          {form.source_type !== "quad" && (
            <label className="col-span-2 text-sm">
              <span className="dm-label">Name</span>
              <input
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Loading Bay Camera"
                className="dm-input"
              />
            </label>
          )}

          {editing?.source_type === "fisheye_view" ? null : form.source_type === "ip" || form.source_type === "fisheye" ? (
            <>
              <label className="text-sm">
                <span className="dm-label">Protocol</span>
                <select
                  value={form.protocol}
                  onChange={(e) => setForm((f) => ({ ...f, protocol: e.target.value as CameraProtocol }))}
                  className="dm-input"
                >
                  <option value="rtsp">rtsp</option>
                  <option value="http">http</option>
                  <option value="https">https</option>
                </select>
              </label>
              <div />
              <label className="text-sm">
                <span className="dm-label">IP address</span>
                <input
                  required
                  value={form.ip}
                  onChange={(e) => setForm((f) => ({ ...f, ip: e.target.value }))}
                  placeholder="192.168.1.50"
                  className="dm-input"
                />
              </label>
              <label className="text-sm">
                <span className="dm-label">Port</span>
                <input
                  required
                  type="number"
                  value={form.port}
                  onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
                  className="dm-input"
                />
              </label>
              <label className="text-sm">
                <span className="dm-label">Compression</span>
                <select
                  value={form.compression}
                  onChange={(e) => setForm((f) => ({ ...f, compression: e.target.value as Compression }))}
                  className="dm-input"
                >
                  <option value="h265">H.265</option>
                  <option value="h264">H.264</option>
                  <option value="jpeg">JPEG</option>
                </select>
              </label>
              <div />
              <label className="col-span-2 text-sm">
                <span className="dm-label">Stream path (optional)</span>
                <div className="flex gap-2">
                  <input
                    value={form.stream_path}
                    onChange={(e) => setForm((f) => ({ ...f, stream_path: e.target.value }))}
                    placeholder={suggestedStreamPath(form.compression)}
                    className="dm-input"
                  />
                  <button
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, stream_path: suggestedStreamPath(f.compression) }))}
                    className="dm-btn-secondary flex-shrink-0 whitespace-nowrap !px-3"
                  >
                    Use suggested
                  </button>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  For a multi-lens camera (e.g. a 4-lens unit), use the <strong>4-Lens Camera</strong>{" "}
                  option above instead &mdash; each lens needs a different path, and this
                  suggestion only matches the first lens. JPEG in particular is often served over
                  HTTP (snapshot/MJPEG) rather than as an RTSP path swap &mdash; if selecting it,
                  you may also need to change Protocol to http and use a path from the camera's own
                  web UI rather than the suggested one.
                </p>
              </label>
              <label className="text-sm">
                <span className="dm-label">Username (optional)</span>
                <input
                  autoComplete="off"
                  value={form.username}
                  onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                  placeholder="admin"
                  className="dm-input"
                />
              </label>
              <label className="text-sm">
                <span className="dm-label">Password (optional)</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder={editing ? "leave blank to keep current" : undefined}
                  className="dm-input"
                />
              </label>
            </>
          ) : form.source_type === "quad" ? (
            <>
              <label className="text-sm">
                <span className="dm-label">IP address</span>
                <input
                  required
                  value={form.ip}
                  onChange={(e) => setForm((f) => ({ ...f, ip: e.target.value }))}
                  placeholder="192.168.1.50"
                  className="dm-input"
                />
              </label>
              <label className="text-sm">
                <span className="dm-label">Port</span>
                <input
                  required
                  type="number"
                  value={form.port}
                  onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))}
                  className="dm-input"
                />
              </label>
              <label className="text-sm">
                <span className="dm-label">Username (optional)</span>
                <input
                  autoComplete="off"
                  value={form.username}
                  onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
                  placeholder="admin"
                  className="dm-input"
                />
              </label>
              <label className="text-sm">
                <span className="dm-label">Password (optional)</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                  className="dm-input"
                />
              </label>

              <div className="col-span-2 space-y-2 rounded-lg bg-slate-800/40 p-3">
                <p className="text-xs font-medium text-slate-400">
                  One row is created per lens, each with its own zones and calibration.
                </p>
                {([1, 2, 3, 4] as const).map((lens) => {
                  const enabled = form.quadEnabled[lens - 1];
                  return (
                    <div key={lens} className="text-sm">
                      <label className="mb-1 flex items-center gap-2 font-medium text-slate-300">
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={(e) =>
                            setForm((f) => {
                              const quadEnabled = [...f.quadEnabled] as FormState["quadEnabled"];
                              quadEnabled[lens - 1] = e.target.checked;
                              return { ...f, quadEnabled };
                            })
                          }
                          className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
                        />
                        Lens {lens} name
                      </label>
                      <input
                        required={enabled}
                        disabled={!enabled}
                        value={form.quadNames[lens - 1]}
                        onChange={(e) =>
                          setForm((f) => {
                            const quadNames = [...f.quadNames] as FormState["quadNames"];
                            quadNames[lens - 1] = e.target.value;
                            return { ...f, quadNames };
                          })
                        }
                        placeholder={`e.g. Lens ${lens}`}
                        className="dm-input disabled:opacity-40"
                      />
                      <span className="mt-1 block font-mono text-xs text-slate-500">
                        {quadLensStreamPath(lens)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <label className="text-sm">
              <span className="dm-label">Device index</span>
              <input
                type="number"
                min={0}
                value={form.device_index}
                onChange={(e) => setForm((f) => ({ ...f, device_index: e.target.value }))}
                className="dm-input"
              />
            </label>
          )}
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={submitting || (!editing && form.source_type === "quad" && form.quadEnabled.every((v) => !v))}
            className="dm-btn-primary"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : editing ? (
              <Save className="h-4 w-4" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            {editing
              ? "Edit Camera"
              : form.source_type === "quad"
                ? `Add Camera (${form.quadEnabled.filter(Boolean).length} row${form.quadEnabled.filter(Boolean).length === 1 ? "" : "s"})`
                : form.source_type === "fisheye"
                  ? "Add Camera & Calibrate"
                  : "Add Camera"}
          </button>
          {editing && (
            <button type="button" onClick={cancelEdit} className="dm-btn-secondary">
              <X className="h-4 w-4" /> Cancel
            </button>
          )}
        </div>
        {!editing && form.source_type === "fisheye" && (
          <p className="text-xs text-slate-500">
            After saving, you'll be sent to Fisheye Setup to mark the circular lens area so
            its feed can be de-warped into a normal-looking view for Live Monitor and detection.
          </p>
        )}
      </form>

      <div className="dm-card overflow-x-auto">
        {loading ? (
          <div className="p-6 text-sm text-slate-400">Loading cameras...</div>
        ) : cameras.length === 0 ? (
          <div className="p-6 text-sm text-slate-400">No cameras registered yet.</div>
        ) : (
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Source</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {cameras.map((camera) => (
                <tr
                  key={camera.id}
                  className={`border-b border-slate-800/60 last:border-0 ${camera.is_enabled ? "" : "opacity-50"} ${
                    editing?.id === camera.id ? "bg-apl-sunset/10" : ""
                  }`}
                >
                  <td className="px-4 py-3 font-medium text-slate-100">{camera.name}</td>
                  <td
                    className="max-w-[320px] truncate px-4 py-3 text-slate-400"
                    title={cameraAddress(camera, cameras)}
                  >
                    {cameraAddress(camera, cameras)}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={statuses[camera.id]?.status ?? "starting"} />
                    {camera.source_type === "fisheye" && camera.fisheye_radius_x == null && (
                      <span className="dm-pill-amber ml-2">not calibrated</span>
                    )}
                    {statuses[camera.id]?.last_error && (
                      <span className="ml-2 text-xs text-slate-500">
                        {statuses[camera.id]?.last_error}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => startEdit(camera)}
                        className={editing?.id === camera.id ? "text-apl-sunset" : "text-slate-500 hover:text-apl-sunset"}
                        title="Edit camera"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      {(camera.source_type === "fisheye" || camera.source_type === "fisheye_view") && (
                        <button
                          onClick={() =>
                            navigate(
                              `/admin/fisheye?camera=${
                                camera.source_type === "fisheye_view" ? camera.fisheye_parent_id : camera.id
                              }`
                            )
                          }
                          className="text-slate-500 hover:text-apl-sunset"
                          title={
                            camera.source_type === "fisheye_view"
                              ? "Edit this view in Fisheye Setup"
                              : "Fisheye calibration and views"
                          }
                        >
                          <Settings2 className="h-4 w-4" />
                        </button>
                      )}
                      <button
                        onClick={() => handleToggleEnabled(camera)}
                        disabled={togglingId === camera.id}
                        className={
                          camera.is_enabled
                            ? "text-slate-500 hover:text-amber-400 disabled:opacity-50"
                            : "text-slate-500 hover:text-emerald-400 disabled:opacity-50"
                        }
                        title={camera.is_enabled ? "Stop camera" : "Start camera"}
                      >
                        {camera.is_enabled ? (
                          <Pause className="h-4 w-4" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </button>
                      <button
                        onClick={() => handleRestart(camera.id)}
                        disabled={restartingId === camera.id || !camera.is_enabled}
                        className="text-slate-500 hover:text-apl-sunset disabled:opacity-50"
                        title={camera.is_enabled ? "Restart camera worker" : "Camera is stopped"}
                      >
                        <RotateCw className={`h-4 w-4 ${restartingId === camera.id ? "animate-spin" : ""}`} />
                      </button>
                      <button
                        onClick={() => handleDelete(camera.id)}
                        className="text-slate-500 hover:text-red-400"
                        title="Remove camera"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
