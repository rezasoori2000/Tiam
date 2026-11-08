import { useCallback, useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import type { AppliesTo, ZoneType, ZoneTypeCreatePayload } from "../types";

const APPLIES_TO_LABEL: Record<AppliesTo, string> = {
  person: "Person",
  vehicle: "Vehicle",
  both: "Both",
};

interface FormState {
  name: string;
  description: string;
  applies_to: AppliesTo;
  rule_exclusion: boolean;
  default_max_speed_kmh: string;
  rule_stop_required: boolean;
  default_stop_min_seconds: string;
  rule_prowling: boolean;
  default_prowling_min_vehicles: string;
  time_restriction_enabled: boolean;
  default_from_time: string;
  default_to_time: string;
}

const INITIAL_FORM: FormState = {
  name: "",
  description: "",
  applies_to: "person",
  rule_exclusion: false,
  default_max_speed_kmh: "",
  rule_stop_required: false,
  default_stop_min_seconds: "1",
  rule_prowling: false,
  default_prowling_min_vehicles: "3",
  time_restriction_enabled: false,
  default_from_time: "",
  default_to_time: "",
};

function toFormState(zt: ZoneType): FormState {
  return {
    name: zt.name,
    description: zt.description ?? "",
    applies_to: zt.applies_to,
    rule_exclusion: zt.rule_exclusion,
    default_max_speed_kmh: zt.default_max_speed_kmh != null ? String(zt.default_max_speed_kmh) : "",
    rule_stop_required: zt.rule_stop_required,
    default_stop_min_seconds: String(zt.default_stop_min_seconds),
    rule_prowling: zt.rule_prowling,
    default_prowling_min_vehicles: String(zt.default_prowling_min_vehicles),
    time_restriction_enabled: zt.time_restriction_enabled,
    default_from_time: zt.default_from_time ?? "",
    default_to_time: zt.default_to_time ?? "",
  };
}

function toPayload(form: FormState): ZoneTypeCreatePayload {
  return {
    name: form.name,
    description: form.description || null,
    applies_to: form.applies_to,
    rule_exclusion: form.rule_exclusion,
    default_max_speed_kmh: form.default_max_speed_kmh ? Number(form.default_max_speed_kmh) : null,
    rule_stop_required: form.rule_stop_required,
    default_stop_min_seconds: Number(form.default_stop_min_seconds) || 1,
    rule_prowling: form.rule_prowling,
    default_prowling_min_vehicles: Number(form.default_prowling_min_vehicles) || 3,
    time_restriction_enabled: form.time_restriction_enabled,
    default_from_time: form.time_restriction_enabled ? form.default_from_time || null : null,
    default_to_time: form.time_restriction_enabled ? form.default_to_time || null : null,
  };
}

function summarizeRules(zt: ZoneType): string {
  const parts: string[] = [];
  if (zt.rule_exclusion) parts.push(`${APPLIES_TO_LABEL[zt.applies_to]} exclusion`);
  if (zt.default_max_speed_kmh != null) parts.push(`Speed limit ${zt.default_max_speed_kmh}km/h`);
  if (zt.rule_stop_required) parts.push(`Must stop ≥ ${zt.default_stop_min_seconds}s`);
  if (zt.rule_prowling) parts.push(`Car prowling (alert at ${zt.default_prowling_min_vehicles})`);
  if (zt.time_restriction_enabled && zt.default_from_time && zt.default_to_time) {
    parts.push(`Active ${zt.default_from_time}-${zt.default_to_time}`);
  }
  return parts.length ? parts.join(" · ") : "No rules set";
}

function ZoneTypeFields({
  form,
  setForm,
}: {
  form: FormState;
  setForm: Dispatch<SetStateAction<FormState>>;
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <label className="col-span-2 text-sm">
        <span className="dm-label">Name</span>
        <input
          required
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="e.g. Loading Dock Exclusion"
          className="dm-input"
        />
      </label>
      <label className="col-span-2 text-sm">
        <span className="dm-label">Description (optional)</span>
        <input
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          className="dm-input"
        />
      </label>

      <label className="text-sm">
        <span className="dm-label">Applies to</span>
        <select
          value={form.applies_to}
          onChange={(e) => setForm((f) => ({ ...f, applies_to: e.target.value as AppliesTo }))}
          className="dm-input"
        >
          <option value="person">Person</option>
          <option value="vehicle">Vehicle</option>
          <option value="both">Both</option>
        </select>
      </label>
      <div />

      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={form.rule_exclusion}
          onChange={(e) => setForm((f) => ({ ...f, rule_exclusion: e.target.checked }))}
          className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
        />
        Exclusion (no entry allowed)
      </label>

      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={form.rule_stop_required}
          onChange={(e) => setForm((f) => ({ ...f, rule_stop_required: e.target.checked }))}
          className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
        />
        Require stop (e.g. stop sign)
      </label>
      {form.rule_stop_required && (
        <label className="text-sm">
          <span className="dm-label">Min stop duration (s)</span>
          <input
            type="number"
            step="0.5"
            value={form.default_stop_min_seconds}
            onChange={(e) =>
              setForm((f) => ({ ...f, default_stop_min_seconds: e.target.value }))
            }
            className="dm-input"
          />
        </label>
      )}

      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={form.rule_prowling}
          onChange={(e) => setForm((f) => ({ ...f, rule_prowling: e.target.checked }))}
          className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
        />
        Car prowling (person going car to car)
      </label>
      {form.rule_prowling && (
        <label className="text-sm">
          <span className="dm-label">Alert at score (cars checked)</span>
          <input
            type="number"
            min="1"
            max="20"
            step="0.5"
            value={form.default_prowling_min_vehicles}
            onChange={(e) => setForm((f) => ({ ...f, default_prowling_min_vehicles: e.target.value }))}
            className="dm-input"
          />
          <span className="mt-1 block text-xs text-muted">Alerts when a person here checks several parked cars, lingers 10 s+ beside one (+0.5) or crouches beside one (+1). Each different car = 1 point. Needs the camera calibrated.</span>
        </label>
      )}



      <label className="text-sm">
        <span className="dm-label">Speed limit (km/h, optional)</span>
        <input
          type="number"
          value={form.default_max_speed_kmh}
          onChange={(e) => setForm((f) => ({ ...f, default_max_speed_kmh: e.target.value }))}
          placeholder="e.g. 10"
          className="dm-input"
        />
      </label>

      <label className="col-span-2 flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          checked={form.time_restriction_enabled}
          onChange={(e) => setForm((f) => ({ ...f, time_restriction_enabled: e.target.checked }))}
          className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
        />
        Restrict to a time window
      </label>
      {form.time_restriction_enabled && (
        <>
          <label className="text-sm">
            <span className="dm-label">From time</span>
            <input
              type="time"
              value={form.default_from_time}
              onChange={(e) => setForm((f) => ({ ...f, default_from_time: e.target.value }))}
              className="dm-input"
            />
          </label>
          <label className="text-sm">
            <span className="dm-label">To time</span>
            <input
              type="time"
              value={form.default_to_time}
              onChange={(e) => setForm((f) => ({ ...f, default_to_time: e.target.value }))}
              className="dm-input"
            />
          </label>
        </>
      )}
    </div>
  );
}

export default function ZoneTypes() {
  const [zoneTypes, setZoneTypes] = useState<ZoneType[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<ZoneType | null>(null);
  const [editForm, setEditForm] = useState<FormState>(INITIAL_FORM);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await api.get<ZoneType[]>("/api/zone-types");
    setZoneTypes(res.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.post("/api/zone-types", toPayload(form));
      setForm(INITIAL_FORM);
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to create zone type");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this zone type? Existing zones created from it keep their current rules.")) return;
    try {
      await api.delete(`/api/zone-types/${id}`);
      await load();
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? "Failed to delete zone type");
    }
  }

  function openEdit(zt: ZoneType) {
    setEditing(zt);
    setEditForm(toFormState(zt));
    setEditError(null);
  }

  async function handleEditSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!editing) return;
    setEditError(null);
    setEditSubmitting(true);
    try {
      await api.put(`/api/zone-types/${editing.id}`, toPayload(editForm));
      setEditing(null);
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setEditError(typeof detail === "string" ? detail : "Failed to update zone type");
    } finally {
      setEditSubmitting(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">Zone Types</h2>
        <p className="mt-1 text-sm text-slate-400">
          Reusable hazard-rule presets (e.g. "Pedestrian Exclusion", "Vehicle Speed Limit
          10km/h"). Pick one when creating a zone in Zone Studio -- its values are copied
          onto that zone and can still be adjusted per-zone afterwards.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="dm-card space-y-4 p-5">
        <ZoneTypeFields form={form} setForm={setForm} />

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button type="submit" disabled={submitting} className="dm-btn-primary">
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Add Zone Type
        </button>
      </form>

      <div className="dm-card">
        {loading ? (
          <div className="p-6 text-sm text-slate-400">Loading zone types...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Rules</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {zoneTypes.map((zt) => (
                <tr key={zt.id} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-100">
                      {zt.name}
                      {zt.is_system && <span className="dm-pill-slate ml-2">Built-in</span>}
                    </div>
                    {zt.description && <div className="text-xs text-slate-500">{zt.description}</div>}
                  </td>
                  <td className="px-4 py-3 text-slate-400">{summarizeRules(zt)}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => openEdit(zt)}
                        className="text-slate-500 hover:text-apl-sunset"
                        title="Edit zone type"
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      {!zt.is_system && (
                        <button
                          onClick={() => handleDelete(zt.id)}
                          className="text-slate-500 hover:text-red-400"
                          title="Delete zone type"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/60 p-4">
          <form onSubmit={handleEditSubmit} className="dm-card w-full max-w-lg space-y-4 p-5">
            <h3 className="text-sm font-semibold text-slate-100">
              Edit {editing.name}
              {editing.is_system && <span className="dm-pill-slate ml-2">Built-in</span>}
            </h3>

            <ZoneTypeFields form={editForm} setForm={setEditForm} />

            {editError && <p className="text-sm text-red-400">{editError}</p>}

            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setEditing(null)} className="dm-btn-secondary">
                Cancel
              </button>
              <button type="submit" disabled={editSubmitting} className="dm-btn-primary">
                {editSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                Save
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
