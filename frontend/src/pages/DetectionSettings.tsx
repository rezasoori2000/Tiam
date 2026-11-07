import { useEffect, useState, type FormEvent } from "react";
import { Loader2, Save } from "lucide-react";
import { api } from "../lib/api";
import type { DetectionSettings, DetectionSettingsUpdatePayload } from "../types";

interface FormState {
  person_confidence: string;
  car_confidence: string;
  truck_confidence: string;
  person_min_aspect_ratio: string;
  detector_imgsz: string;
  confirmation_min_observations: string;
  confirmation_window_frames: string;
  ignore_person_shadows: boolean;
}

// Mirrors the backend model's column defaults (models.DetectionSettings).
const CONFIRMATION_DEFAULTS = { min_observations: 3, window_frames: 6 };

function toFormState(s: DetectionSettings): FormState {
  return {
    person_confidence: String(s.person_confidence),
    car_confidence: String(s.car_confidence),
    truck_confidence: String(s.truck_confidence),
    person_min_aspect_ratio: String(s.person_min_aspect_ratio),
    detector_imgsz: String(s.detector_imgsz),
    confirmation_min_observations: String(s.confirmation_min_observations),
    confirmation_window_frames: String(s.confirmation_window_frames),
    ignore_person_shadows: s.ignore_person_shadows,
  };
}

function toPayload(f: FormState): DetectionSettingsUpdatePayload {
  return {
    person_confidence: Number(f.person_confidence),
    car_confidence: Number(f.car_confidence),
    truck_confidence: Number(f.truck_confidence),
    person_min_aspect_ratio: Number(f.person_min_aspect_ratio),
    detector_imgsz: Number(f.detector_imgsz),
    confirmation_min_observations: Math.max(1, Math.round(Number(f.confirmation_min_observations))),
    confirmation_window_frames: Math.max(1, Math.round(Number(f.confirmation_window_frames))),
    ignore_person_shadows: f.ignore_person_shadows,
  };
}

function ConfidenceField({
  label, value, onChange, min = "0.01",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  min?: string;
}) {
  return (
    <label className="text-sm">
      <span className="dm-label">{label}</span>
      <input
        type="number"
        min={min}
        max="1"
        step="0.01"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="dm-input"
      />
    </label>
  );
}

export default function DetectionSettingsPage() {
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get<DetectionSettings>("/api/detection-settings").then((res) => {
      setForm(toFormState(res.data));
      setLoading(false);
    });
  }, []);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!form) return;
    setError(null);
    setSaved(false);
    if (Number(form.confirmation_min_observations) > Number(form.confirmation_window_frames)) {
      setError("Minimum confirmations can't be greater than the sliding window size.");
      return;
    }
    setSaving(true);
    try {
      const res = await api.put<DetectionSettings>("/api/detection-settings", toPayload(form));
      setForm(toFormState(res.data));
      setSaved(true);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to save detection settings");
    } finally {
      setSaving(false);
    }
  }

  if (loading || !form) {
    return <div className="p-6 text-sm text-slate-400">Loading detection settings...</div>;
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">Detection Settings</h2>
        <p className="mt-1 text-sm text-slate-400">
          Global tuning knobs for the detection pipeline, applied to every camera. Saving
          restarts all camera workers so the new values take effect immediately.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="dm-card space-y-4 p-5">
          <h3 className="text-sm font-semibold text-slate-100">Confidence thresholds</h3>
          <p className="text-xs text-slate-500">
            Minimum detection confidence (0-1) required to keep a box, per object type. Raise
            a class's threshold if it's showing false positives; lower it if real objects of
            that type are being missed.
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <ConfidenceField
              label="Human"
              value={form.person_confidence}
              onChange={(v) => setForm((f) => f && { ...f, person_confidence: v })}
            />
            <ConfidenceField
              label="Car"
              value={form.car_confidence}
              onChange={(v) => setForm((f) => f && { ...f, car_confidence: v })}
            />
            <ConfidenceField
              label="Truck"
              value={form.truck_confidence}
              onChange={(v) => setForm((f) => f && { ...f, truck_confidence: v })}
            />
          </div>
        </section>

        <section className="dm-card space-y-4 p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-100">Incident confirmation</h3>
            <button
              type="button"
              className="text-xs text-apl-sunset hover:underline"
              onClick={() =>
                setForm(
                  (f) =>
                    f && {
                      ...f,
                      confirmation_min_observations: String(CONFIRMATION_DEFAULTS.min_observations),
                      confirmation_window_frames: String(CONFIRMATION_DEFAULTS.window_frames),
                    }
                )
              }
            >
              Reset to defaults
            </button>
          </div>
          <p className="text-xs text-slate-500">
            A detection must be seen in at least N of the last M processed frames, for the same
            tracked object, before it's saved as an incident. Higher values mean fewer false/
            transient alerts (a person momentarily turning away from the camera, a one-frame
            tracker glitch), but logging is delayed slightly until the count is reached. Applies
            to every rule type (exclusion, speeding).
          </p>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="dm-label">Minimum confirmations (N)</span>
              <input
                type="number"
                min="1"
                max="30"
                step="1"
                value={form.confirmation_min_observations}
                onChange={(e) =>
                  setForm((f) => f && { ...f, confirmation_min_observations: e.target.value })
                }
                className="dm-input"
              />
              <span className="mt-1 block text-xs text-slate-500">
                N. Set to 1 to save on first sighting (old behavior). Range 1-30.
              </span>
            </label>
            <label className="text-sm">
              <span className="dm-label">Sliding window (frames)</span>
              <input
                type="number"
                min="1"
                max="60"
                step="1"
                value={form.confirmation_window_frames}
                onChange={(e) =>
                  setForm((f) => f && { ...f, confirmation_window_frames: e.target.value })
                }
                className="dm-input"
              />
              <span className="mt-1 block text-xs text-slate-500">
                M. Must be &gt;= N. Range 1-60.
              </span>
            </label>
          </div>
        </section>

        <section className="dm-card space-y-4 p-5">
          <h3 className="text-sm font-semibold text-slate-100">Other tuning</h3>
          <p className="text-xs text-slate-500">
            A few more knobs worth experimenting with if you're chasing better accuracy or
            performance.
          </p>
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={form.ignore_person_shadows}
              onChange={(e) => setForm((f) => f && { ...f, ignore_person_shadows: e.target.checked })}
              className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
            />
            Ignore human shadows
          </label>
          <p className="-mt-2 ml-6 text-xs text-slate-500">
            Drops a "person" detection touching another person when it's just darker floor -- their
            shadow -- so it can't raise exclusion alerts.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">
              <span className="dm-label">Detection resolution</span>
              <select
                value={form.detector_imgsz}
                onChange={(e) => setForm((f) => f && { ...f, detector_imgsz: e.target.value })}
                className="dm-input"
              >
                {[...new Set([320, 480, 640, 800, 960, 1280, 1600, 1920, Number(form.detector_imgsz)])]
                  .sort((a, b) => a - b)
                  .map((px) => (
                    <option key={px} value={px}>
                      {px} px{px === 960 ? " (default)" : ""}
                    </option>
                  ))}
              </select>
              <span className="mt-1 block text-xs text-slate-500">
                Input size for the main person/vehicle detector. Higher = better at small/distant
                people but uses more GPU; lower = faster. Doesn't affect zones or the live view.
              </span>
            </label>
            <label className="text-sm">
              <span className="dm-label">Min person height/width ratio</span>
              <input
                type="number"
                min="0"
                step="0.1"
                value={form.person_min_aspect_ratio}
                onChange={(e) =>
                  setForm((f) => f && { ...f, person_min_aspect_ratio: e.target.value })
                }
                className="dm-input"
              />
              <span className="mt-1 block text-xs text-slate-500">
                Drops "person" boxes that aren't tall enough to plausibly be a human (e.g. bins).
                Set to 0 to disable.
              </span>
            </label>
          </div>
        </section>

        {error && <p className="text-sm text-red-400">{error}</p>}
        {saved && !error && <p className="text-sm text-emerald-400">Saved -- cameras restarting.</p>}

        <button type="submit" disabled={saving} className="dm-btn-primary">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Save Settings
        </button>
      </form>
    </div>
  );
}
