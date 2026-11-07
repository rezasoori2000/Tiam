import { useEffect, useState, type FormEvent } from "react";
import { Loader2, Save } from "lucide-react";
import { api } from "../lib/api";
import type { Site, SiteType } from "../types";

// Admin: this server's site (one Tiam server per site, ADR 0004). The after-hours window is
// what night-time rules use; zones can still set their own time windows.
export default function SiteSettings() {
  const [site, setSite] = useState<Site | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .get<Site[]>("/api/sites")
      .then((r) => setSite(r.data[0] ?? null))
      .catch(() => setError("Couldn't load the site"));
  }, []);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!site) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const { id, ...body } = site;
      const r = await api.put<Site>(`/api/sites/${id}`, {
        ...body,
        max_stay_hours: body.max_stay_hours || null,
      });
      setSite(r.data);
      setSaved(true);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to save (check the times are HH:MM)");
    } finally {
      setSaving(false);
    }
  }

  if (!site) {
    return error ? <p className="text-sm text-critical">{error}</p> : <div className="dm-skeleton h-60 max-w-3xl" />;
  }

  const set = <K extends keyof Site>(key: K, value: Site[K]) => setSite((s) => s && { ...s, [key]: value });

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-fg">Site</h2>
        <p className="mt-1 text-sm text-muted">The car park this server monitors.</p>
      </div>
      <form onSubmit={handleSubmit} className="dm-card space-y-4 p-5">
        <div className="grid grid-cols-2 gap-3">
          <label className="col-span-2 text-sm">
            <span className="dm-label">Name</span>
            <input required value={site.name} onChange={(e) => set("name", e.target.value)} className="dm-input" />
          </label>
          <label className="text-sm">
            <span className="dm-label">Type</span>
            <select value={site.site_type} onChange={(e) => set("site_type", e.target.value as SiteType)} className="dm-input">
              <option value="hospital">Hospital</option>
              <option value="mall">Shopping mall</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="dm-label">Time zone</span>
            <input value={site.timezone} onChange={(e) => set("timezone", e.target.value)} className="dm-input" />
          </label>
          <label className="text-sm">
            <span className="dm-label">After hours from</span>
            <input type="time" required value={site.after_hours_from}
              onChange={(e) => set("after_hours_from", e.target.value)} className="dm-input" />
          </label>
          <label className="text-sm">
            <span className="dm-label">After hours to</span>
            <input type="time" required value={site.after_hours_to}
              onChange={(e) => set("after_hours_to", e.target.value)} className="dm-input" />
          </label>
          <p className="col-span-2 -mt-1 text-xs text-muted">
            Night window for after-hours rules (wraps past midnight, e.g. 20:00 to 06:00).
          </p>
          <label className="text-sm">
            <span className="dm-label">Max stay (hours, optional)</span>
            <input type="number" min="0" step="0.5" value={site.max_stay_hours ?? ""}
              onChange={(e) => set("max_stay_hours", e.target.value === "" ? null : Number(e.target.value))}
              className="dm-input" />
          </label>
        </div>
        {error && <p className="text-sm text-critical">{error}</p>}
        {saved && !error && <p className="text-sm text-success">Saved.</p>}
        <button type="submit" disabled={saving} className="dm-btn-primary">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save
        </button>
      </form>
    </div>
  );
}
