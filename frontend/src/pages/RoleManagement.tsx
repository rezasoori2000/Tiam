import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { PAGE_KEYS, PAGE_LABELS } from "../types";
import type { Role, RoleCreatePayload } from "../types";

interface FormState {
  name: string;
  pages: string[];
}

const INITIAL_FORM: FormState = { name: "", pages: [] };

export default function RoleManagement() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await api.get<Role[]>("/api/roles");
    setRoles(res.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function togglePage(page: string) {
    setForm((f) => ({
      ...f,
      pages: f.pages.includes(page) ? f.pages.filter((p) => p !== page) : [...f.pages, page],
    }));
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const payload: RoleCreatePayload = { name: form.name, pages: form.pages };
      await api.post("/api/roles", payload);
      setForm(INITIAL_FORM);
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Failed to create role");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this role?")) return;
    try {
      await api.delete(`/api/roles/${id}`);
      await load();
    } catch (err: any) {
      alert(err?.response?.data?.detail ?? "Failed to delete role");
    }
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">Role Management</h2>
        <p className="mt-1 text-sm text-slate-400">
          Create roles and choose which pages users assigned to that role can see. The
          built-in Admin role always has full access and isn't shown here.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="dm-card space-y-4 p-5">
        <label className="block text-sm">
          <span className="dm-label">Role name</span>
          <input
            required
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="e.g. Site Supervisor"
            className="dm-input"
          />
        </label>

        <div>
          <span className="dm-label">Visible pages</span>
          <div className="mt-1 grid grid-cols-2 gap-2">
            {PAGE_KEYS.map((page) => (
              <label key={page} className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={form.pages.includes(page)}
                  onChange={() => togglePage(page)}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-800 text-apl-sunset"
                />
                {PAGE_LABELS[page]}
              </label>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <button type="submit" disabled={submitting} className="dm-btn-primary">
          {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Add Role
        </button>
      </form>

      <div className="dm-card">
        {loading ? (
          <div className="p-6 text-sm text-slate-400">Loading roles...</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-slate-500">
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Pages</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.id} className="border-b border-slate-800/60 last:border-0">
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-100">
                      {r.name}
                      {r.is_system && <span className="dm-pill-slate ml-2">Built-in</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {r.is_system
                      ? "All pages"
                      : r.pages.length
                        ? r.pages.map((p) => PAGE_LABELS[p] ?? p).join(", ")
                        : "None"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!r.is_system && (
                      <button
                        onClick={() => handleDelete(r.id)}
                        className="text-slate-500 hover:text-red-400"
                        title="Delete role"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
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
